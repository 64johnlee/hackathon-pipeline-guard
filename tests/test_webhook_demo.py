"""Tests for the /demo endpoints (GET + POST) and landing page integrity."""
from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from pipelineguard.models import DiagnosisReport, FailureCategory, FixProposal


class StubAgent:
    """Records diagnose() calls and returns a fixed report."""

    def __init__(self, *args, **kwargs) -> None:
        self.calls: list[dict] = []
        StubAgent.last_instance = self

    async def diagnose(self, project, pipeline_id=None, post_comment=False, **kw):
        self.calls.append(
            {"project": project, "pipeline_id": pipeline_id, "post_comment": post_comment}
        )
        return DiagnosisReport(
            project=project,
            pipeline_id=pipeline_id,
            root_cause="stub root cause",
            failure_category=FailureCategory.CONFIG_ERROR,
            affected_jobs=["build"],
            fix_proposals=[FixProposal(file_path="a.txt", description="fix it")],
            full_analysis="stub analysis",
        )


@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setattr("pipelineguard.agent.PipelineGuardAgent", StubAgent)
    from pipelineguard.webhook import make_app

    app = make_app(gemini_api_key="test-key", gitlab_token="test-token")
    return TestClient(app)


def test_get_demo_no_params_redirects_to_landing(client):
    resp = client.get("/demo", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "/"


def test_get_demo_scenario_returns_canned(client):
    resp = client.get("/demo", params={"scenario": "flaky"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["is_flaky"] is True
    assert data["category"] == "flaky"


def test_post_demo_canned_scenario(client):
    resp = client.post("/demo", json={"project": "demo", "scenario": "config"})
    assert resp.status_code == 200
    assert resp.json()["category"] == "config_error"


def test_post_demo_unknown_scenario_falls_back(client):
    resp = client.post("/demo", json={"project": "demo", "scenario": "nope"})
    assert resp.status_code == 200
    assert resp.json()["category"] == "env_var_missing"


def test_post_demo_real_project_runs_diagnosis(client):
    resp = client.post("/demo", json={"project": "org/repo", "pipeline_id": 42})
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_cause"] == "stub root cause"
    assert data["category"] == "config_error"
    assert data["fix_proposals"][0]["file_path"] == "a.txt"
    call = StubAgent.last_instance.calls[-1]
    assert call == {"project": "org/repo", "pipeline_id": 42, "post_comment": False}


def test_post_demo_real_project_without_pid_uses_latest_failed(client):
    resp = client.post("/demo", json={"project": "org/repo"})
    assert resp.status_code == 200
    assert StubAgent.last_instance.calls[-1]["pipeline_id"] is None


def test_get_demo_real_project_with_pid(client):
    resp = client.get("/demo", params={"project": "org/repo", "pipeline_id": "7"})
    assert resp.status_code == 200
    assert StubAgent.last_instance.calls[-1]["pipeline_id"] == 7


def test_post_demo_missing_project_422(client):
    resp = client.post("/demo", json={})
    assert resp.status_code == 422


def test_post_demo_bad_pipeline_id_422(client):
    resp = client.post("/demo", json={"project": "org/repo", "pipeline_id": "abc"})
    assert resp.status_code == 422


def test_landing_page_script_has_no_broken_escapes(client):
    resp = client.get("/")
    assert resp.status_code == 200
    script = re.search(r"<script>(.*?)</script>", resp.text, re.S).group(1)
    assert "\\`" not in script
    assert "loadPreset" in script


def test_pricing_page_renders_without_doubled_braces(client):
    resp = client.get("/pricing")
    assert resp.status_code == 200
    assert "{{" not in resp.text and "}}" not in resp.text
    assert "function subscribe" in resp.text


def test_webhook_ignores_non_pipeline_events(client):
    resp = client.post("/webhook/gitlab", json={"object_kind": "push"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"


def test_webhook_ignores_non_failed_pipeline(client):
    payload = {
        "object_kind": "pipeline",
        "object_attributes": {"status": "success", "id": 1},
        "project": {"path_with_namespace": "org/repo"},
    }
    resp = client.post("/webhook/gitlab", json=payload)
    assert resp.status_code == 200
    assert resp.json()["status"] == "ignored"
    assert "success" in resp.json()["reason"]


def test_webhook_returns_500_on_missing_project(client):
    payload = {
        "object_kind": "pipeline",
        "object_attributes": {"status": "failed", "id": 1},
        "project": {},
    }
    resp = client.post("/webhook/gitlab", json=payload)
    assert resp.status_code == 500


def test_health_endpoint_has_service_field(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "PipelineGuard"
    assert "backend" in data


# ---------------------------------------------------------------------------
# /api/diagnose  (UiPath DiagnoseWithAI.xaml endpoint)
# ---------------------------------------------------------------------------


def test_api_diagnose_returns_full_report(client):
    resp = client.post("/api/diagnose", json={"project": "org/repo", "pipeline_id": 99})
    assert resp.status_code == 200
    data = resp.json()
    assert data["root_cause"] == "stub root cause"
    assert "failure_category" in data
    assert "fix_proposals" in data
    call = StubAgent.last_instance.calls[-1]
    assert call["project"] == "org/repo"
    assert call["pipeline_id"] == 99
    assert call["post_comment"] is False


def test_api_diagnose_missing_project_422(client):
    resp = client.post("/api/diagnose", json={})
    assert resp.status_code == 422


def test_api_diagnose_bad_pipeline_id_422(client):
    resp = client.post("/api/diagnose", json={"project": "org/repo", "pipeline_id": "bad"})
    assert resp.status_code == 422
