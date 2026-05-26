"""Tests for pipelineguard.ingesters.gitlab_to_splunk."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import gitlab.exceptions
import httpx
import pytest

from pipelineguard.ingesters.gitlab_to_splunk import (
    GitLabToSplunkIngester,
    IngestStats,
    _to_epoch,
    parse_since,
)


# ---------------------------------------------------------------------------
# parse_since
# ---------------------------------------------------------------------------

class TestParseSince:
    def test_relative_days(self) -> None:
        now = datetime.now(timezone.utc)
        result = parse_since("-7d")
        assert abs((now - result - timedelta(days=7)).total_seconds()) < 5

    def test_relative_hours(self) -> None:
        now = datetime.now(timezone.utc)
        result = parse_since("-24h")
        assert abs((now - result - timedelta(hours=24)).total_seconds()) < 5

    def test_relative_minutes(self) -> None:
        now = datetime.now(timezone.utc)
        result = parse_since("-30m")
        assert abs((now - result - timedelta(minutes=30)).total_seconds()) < 5

    def test_relative_seconds(self) -> None:
        now = datetime.now(timezone.utc)
        result = parse_since("-90s")
        assert abs((now - result - timedelta(seconds=90)).total_seconds()) < 5

    def test_relative_weeks(self) -> None:
        now = datetime.now(timezone.utc)
        result = parse_since("-2w")
        assert abs((now - result - timedelta(weeks=2)).total_seconds()) < 5

    def test_iso_with_z(self) -> None:
        assert parse_since("2026-05-20T00:00:00Z") == datetime(
            2026, 5, 20, tzinfo=timezone.utc
        )

    def test_iso_with_offset(self) -> None:
        assert parse_since("2026-05-20T00:00:00+00:00") == datetime(
            2026, 5, 20, tzinfo=timezone.utc
        )

    def test_iso_naive_assumes_utc(self) -> None:
        result = parse_since("2026-05-20T00:00:00")
        assert result == datetime(2026, 5, 20, tzinfo=timezone.utc)

    def test_invalid_raises(self) -> None:
        with pytest.raises(ValueError, match="not a recognized format"):
            parse_since("garbage")

    def test_empty_string_raises(self) -> None:
        with pytest.raises(ValueError):
            parse_since("")


# ---------------------------------------------------------------------------
# _to_epoch
# ---------------------------------------------------------------------------

class TestToEpoch:
    def test_none_returns_none(self) -> None:
        assert _to_epoch(None) is None

    def test_int_passthrough(self) -> None:
        assert _to_epoch(1748332800) == 1748332800.0

    def test_float_passthrough(self) -> None:
        assert _to_epoch(1748332800.5) == 1748332800.5

    def test_iso_string(self) -> None:
        expected = datetime(2026, 5, 27, 8, 0, tzinfo=timezone.utc).timestamp()
        assert _to_epoch("2026-05-27T08:00:00Z") == expected

    def test_bad_string_returns_none(self) -> None:
        assert _to_epoch("not-a-date") is None

    def test_unsupported_type_returns_none(self) -> None:
        assert _to_epoch(["a", "list"]) is None


# ---------------------------------------------------------------------------
# Ingester construction
# ---------------------------------------------------------------------------

class TestIngesterInit:
    def test_missing_hec_token_raises(self) -> None:
        with pytest.raises(ValueError, match="hec_token is required"):
            GitLabToSplunkIngester(gitlab_token="x", hec_token="")

    @patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
    def test_hec_url_trailing_slash_stripped(self, _gl: MagicMock) -> None:
        ing = GitLabToSplunkIngester(
            gitlab_token="x",
            hec_url="https://splunk:8088/",
            hec_token="t",
        )
        assert ing._hec_collector_url == "https://splunk:8088/services/collector/event"

    @patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
    def test_hec_auth_header_format(self, _gl: MagicMock) -> None:
        ing = GitLabToSplunkIngester(
            gitlab_token="x", hec_url="https://h:8088", hec_token="sekret"
        )
        assert ing._hec_headers["Authorization"] == "Splunk sekret"
        assert ing._hec_headers["Content-Type"] == "application/json"


# ---------------------------------------------------------------------------
# Event construction
# ---------------------------------------------------------------------------

def _make_pipeline(**overrides) -> MagicMock:
    pipeline = MagicMock()
    pipeline.id = 42
    pipeline.status = "failed"
    pipeline.ref = "main"
    pipeline.sha = "abc1234"
    pipeline.web_url = "https://gitlab.com/demo/repo/-/pipelines/42"
    pipeline.created_at = "2026-05-27T08:00:00Z"
    pipeline.updated_at = "2026-05-27T08:05:00Z"
    pipeline.duration = 300
    pipeline.user = {"username": "alice"}
    for k, v in overrides.items():
        setattr(pipeline, k, v)
    return pipeline


def _make_job(**overrides) -> MagicMock:
    job = MagicMock()
    job.id = 1001
    job.name = "deploy"
    job.stage = "deploy"
    job.status = "failed"
    job.failure_reason = "script_failure"
    job.started_at = "2026-05-27T08:01:00Z"
    job.finished_at = "2026-05-27T08:04:00Z"
    job.duration = 180.0
    job.web_url = "https://gitlab.com/demo/repo/-/jobs/1001"
    for k, v in overrides.items():
        setattr(job, k, v)
    return job


@patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
class TestEventShapes:
    def _make_ingester(self) -> GitLabToSplunkIngester:
        return GitLabToSplunkIngester(
            gitlab_token="x", hec_url="https://h:8088", hec_token="t"
        )

    def test_pipeline_event_shape(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        event = ing._pipeline_event("demo/repo", _make_pipeline())
        assert event["index"] == "pipelineguard"
        assert event["sourcetype"] == "gitlab:pipeline"
        assert event["time"] is not None
        e = event["event"]
        assert e["pipeline_id"] == 42
        assert e["project"] == "demo/repo"
        assert e["status"] == "failed"
        assert e["ref"] == "main"
        assert e["sha"] == "abc1234"
        assert e["user"] == "alice"
        assert e["duration"] == 300

    def test_pipeline_event_user_missing(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        event = ing._pipeline_event("demo/repo", _make_pipeline(user=None))
        assert event["event"]["user"] is None

    def test_failed_job_includes_log_tail(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        project = MagicMock()
        project.jobs.get.return_value.trace.return_value = b"line1\nline2\nERROR boom\n"
        event = ing._job_event(
            "demo/repo", _make_pipeline(), _make_job(status="failed"), project
        )
        assert event["sourcetype"] == "gitlab:job"
        assert "ERROR boom" in event["event"]["log_tail"]
        assert event["event"]["failure_reason"] == "script_failure"

    def test_canceled_job_includes_log_tail(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        project = MagicMock()
        project.jobs.get.return_value.trace.return_value = "canceled output"
        event = ing._job_event(
            "demo/repo", _make_pipeline(), _make_job(status="canceled"), project
        )
        assert event["event"]["log_tail"] == "canceled output"

    def test_success_job_omits_log_tail(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        project = MagicMock()
        event = ing._job_event(
            "demo/repo", _make_pipeline(), _make_job(status="success"), project
        )
        assert event["event"]["log_tail"] == ""
        project.jobs.get.assert_not_called()

    def test_log_tail_truncates_to_last_n_lines(self, _gl: MagicMock) -> None:
        ing = GitLabToSplunkIngester(
            gitlab_token="x",
            hec_url="https://h:8088",
            hec_token="t",
            log_tail_lines=3,
        )
        project = MagicMock()
        project.jobs.get.return_value.trace.return_value = "\n".join(
            f"line{i}" for i in range(1, 11)
        )
        event = ing._job_event(
            "demo/repo", _make_pipeline(), _make_job(status="failed"), project
        )
        tail_lines = event["event"]["log_tail"].splitlines()
        assert tail_lines == ["line8", "line9", "line10"]

    def test_log_tail_handles_fetch_error(self, _gl: MagicMock) -> None:
        ing = self._make_ingester()
        project = MagicMock()
        project.jobs.get.side_effect = gitlab.exceptions.GitlabGetError(
            "not found", response_code=404
        )
        event = ing._job_event(
            "demo/repo", _make_pipeline(), _make_job(status="failed"), project
        )
        assert event["event"]["log_tail"] == ""


# ---------------------------------------------------------------------------
# HEC POST
# ---------------------------------------------------------------------------

@patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
class TestPostBatch:
    def _make_ingester(self) -> GitLabToSplunkIngester:
        return GitLabToSplunkIngester(
            gitlab_token="x", hec_url="https://h:8088", hec_token="t"
        )

    @patch("pipelineguard.ingesters.gitlab_to_splunk.httpx.Client")
    def test_success_returns_event_count(
        self, mock_client_cls: MagicMock, _gl: MagicMock
    ) -> None:
        ing = self._make_ingester()
        events = [
            {"time": 1.0, "index": "pipelineguard", "sourcetype": "x", "event": {"a": 1}},
            {"time": 2.0, "index": "pipelineguard", "sourcetype": "x", "event": {"a": 2}},
        ]
        stats = IngestStats()

        mock_client = MagicMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value.__enter__.return_value = mock_client

        count = ing._post_batch(events, stats)

        assert count == 2
        assert stats.hec_errors == 0
        call = mock_client.post.call_args
        assert call.args[0] == "https://h:8088/services/collector/event"
        assert call.kwargs["headers"]["Authorization"] == "Splunk t"
        body_lines = call.kwargs["content"].splitlines()
        assert len(body_lines) == 2
        for line in body_lines:
            json.loads(line)  # must parse

    @patch("pipelineguard.ingesters.gitlab_to_splunk.httpx.Client")
    def test_http_error_increments_stats(
        self, mock_client_cls: MagicMock, _gl: MagicMock
    ) -> None:
        ing = self._make_ingester()
        stats = IngestStats()

        mock_client = MagicMock()
        mock_client.post.side_effect = httpx.HTTPError("boom")
        mock_client_cls.return_value.__enter__.return_value = mock_client

        count = ing._post_batch([{"event": {}}], stats)
        assert count == 0
        assert stats.hec_errors == 1


# ---------------------------------------------------------------------------
# End-to-end ingest_project
# ---------------------------------------------------------------------------

@patch("pipelineguard.ingesters.gitlab_to_splunk.httpx.Client")
@patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
def test_ingest_project_happy_path(
    mock_gitlab_cls: MagicMock, mock_client_cls: MagicMock
) -> None:
    p = _make_pipeline()
    failed_job = _make_job(status="failed", id=1001, name="deploy")
    ok_job = _make_job(status="success", id=1002, name="test", failure_reason=None)
    p.jobs.list.return_value = [failed_job, ok_job]

    project = MagicMock()
    project.pipelines.list.return_value = iter([p])
    project.jobs.get.return_value.trace.return_value = b"build log\nERROR boom"

    gl_instance = MagicMock()
    gl_instance.projects.get.return_value = project
    mock_gitlab_cls.return_value = gl_instance

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    ing = GitLabToSplunkIngester(
        gitlab_token="x", hec_url="https://h:8088", hec_token="t"
    )
    stats = ing.ingest_project("demo/repo", since="-7d")

    assert stats.pipelines == 1
    assert stats.jobs == 2
    assert stats.events_posted == 3
    assert stats.hec_errors == 0

    body = mock_client.post.call_args.kwargs["content"]
    assert "gitlab:pipeline" in body
    assert "gitlab:job" in body
    parsed = [json.loads(line) for line in body.splitlines()]
    job_events = [e for e in parsed if e["sourcetype"] == "gitlab:job"]
    failed_evt = next(e for e in job_events if e["event"]["status"] == "failed")
    ok_evt = next(e for e in job_events if e["event"]["status"] == "success")
    assert "ERROR boom" in failed_evt["event"]["log_tail"]
    assert ok_evt["event"]["log_tail"] == ""


@patch("pipelineguard.ingesters.gitlab_to_splunk.httpx.Client")
@patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
def test_ingest_project_max_pipelines_cap(
    mock_gitlab_cls: MagicMock, mock_client_cls: MagicMock
) -> None:
    pipelines = [_make_pipeline(id=i) for i in range(10)]
    for p in pipelines:
        p.jobs.list.return_value = []

    project = MagicMock()
    project.pipelines.list.return_value = iter(pipelines)

    gl_instance = MagicMock()
    gl_instance.projects.get.return_value = project
    mock_gitlab_cls.return_value = gl_instance

    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_client = MagicMock()
    mock_client.post.return_value = mock_resp
    mock_client_cls.return_value.__enter__.return_value = mock_client

    ing = GitLabToSplunkIngester(
        gitlab_token="x", hec_url="https://h:8088", hec_token="t"
    )
    stats = ing.ingest_project("demo/repo", since="-7d", max_pipelines=3)

    assert stats.pipelines == 3
    assert stats.jobs == 0


@patch("pipelineguard.ingesters.gitlab_to_splunk.gitlab.Gitlab")
def test_ingest_project_empty(mock_gitlab_cls: MagicMock) -> None:
    project = MagicMock()
    project.pipelines.list.return_value = iter([])

    gl_instance = MagicMock()
    gl_instance.projects.get.return_value = project
    mock_gitlab_cls.return_value = gl_instance

    ing = GitLabToSplunkIngester(
        gitlab_token="x", hec_url="https://h:8088", hec_token="t"
    )
    stats = ing.ingest_project("demo/repo", since="-7d")

    assert stats.pipelines == 0
    assert stats.jobs == 0
    assert stats.events_posted == 0
    assert stats.hec_errors == 0
