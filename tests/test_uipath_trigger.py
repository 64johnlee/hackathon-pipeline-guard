"""Tests for the UiPath Maestro trigger path in handle_pipeline_event."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from pipelineguard import webhook
from pipelineguard.webhook import _uipath_get_token, handle_pipeline_event

PAYLOAD = {
    "object_kind": "pipeline",
    "object_attributes": {"status": "failed", "id": 42},
    "project": {"path_with_namespace": "org/repo"},
}


class StubAgent:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def diagnose(self, project, pipeline_id=None, post_comment=False, **kw):
        self.calls.append({"project": project, "pipeline_id": pipeline_id})
        return SimpleNamespace(root_cause="stub", failure_category=None, mr_comment_url=None)


class StubResponse:
    def __init__(self, json_data=None, error: Exception | None = None) -> None:
        self._json = json_data or {}
        self._error = error

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error

    def json(self) -> dict:
        return self._json


class StubAsyncClient:
    """Drop-in for httpx.AsyncClient; records posts, returns queued responses."""

    posts: list[dict] = []
    responses: list[StubResponse] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, **kwargs):
        StubAsyncClient.posts.append({"url": url, **kwargs})
        return StubAsyncClient.responses.pop(0)


def _patch_httpx(monkeypatch, responses):
    StubAsyncClient.posts = []
    StubAsyncClient.responses = list(responses)
    monkeypatch.setattr(webhook, "httpx", SimpleNamespace(AsyncClient=StubAsyncClient))


def test_trigger_success_skips_local_diagnosis(monkeypatch):
    _patch_httpx(monkeypatch, [StubResponse()])
    agent = StubAgent()
    result = asyncio.run(
        handle_pipeline_event(
            PAYLOAD,
            agent,
            uipath_token="static-token",
            uipath_trigger_url="https://example.test/trigger",
        )
    )
    assert result["status"] == "triggered_uipath"
    assert result["pipeline_id"] == "42"
    assert agent.calls == []
    assert StubAsyncClient.posts[0]["url"] == "https://example.test/trigger"
    assert StubAsyncClient.posts[0]["headers"]["Authorization"] == "Bearer static-token"


def test_trigger_failure_falls_back_to_diagnosis(monkeypatch):
    _patch_httpx(monkeypatch, [StubResponse(error=RuntimeError("boom"))])
    agent = StubAgent()
    result = asyncio.run(
        handle_pipeline_event(
            PAYLOAD,
            agent,
            uipath_token="static-token",
            uipath_trigger_url="https://example.test/trigger",
        )
    )
    assert result["status"] == "diagnosed"
    assert agent.calls == [{"project": "org/repo", "pipeline_id": 42}]


def test_no_uipath_config_goes_straight_to_diagnosis(monkeypatch):
    _patch_httpx(monkeypatch, [])
    agent = StubAgent()
    result = asyncio.run(handle_pipeline_event(PAYLOAD, agent))
    assert result["status"] == "diagnosed"
    assert StubAsyncClient.posts == []


def test_oauth_exchange_used_when_no_static_token(monkeypatch):
    _patch_httpx(
        monkeypatch,
        [StubResponse(json_data={"access_token": "oauth-tok"}), StubResponse()],
    )
    agent = StubAgent()
    result = asyncio.run(
        handle_pipeline_event(
            PAYLOAD,
            agent,
            uipath_client_id="cid",
            uipath_client_secret="csec",
            uipath_trigger_url="https://example.test/trigger",
        )
    )
    assert result["status"] == "triggered_uipath"
    token_post, trigger_post = StubAsyncClient.posts
    assert token_post["url"].endswith("/identity_/connect/token")
    assert token_post["data"]["grant_type"] == "client_credentials"
    assert trigger_post["headers"]["Authorization"] == "Bearer oauth-tok"


def test_uipath_get_token_returns_access_token(monkeypatch):
    _patch_httpx(monkeypatch, [StubResponse(json_data={"access_token": "tok-123"})])
    token = asyncio.run(_uipath_get_token("cid", "csec"))
    assert token == "tok-123"
    assert StubAsyncClient.posts[0]["data"]["scope"] == "OR.Jobs OR.Jobs.Execute"
