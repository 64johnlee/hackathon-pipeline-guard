"""Pump GitLab CI pipeline + job events into Splunk via HEC.

The SplunkGuard agent queries Splunk for pipeline history; this module is how
the data gets there. Reads pipelines/jobs through python-gitlab and posts
newline-delimited JSON events to the Splunk HTTP Event Collector.

Event shapes (sent as the `event` field of HEC payloads):

    sourcetype="gitlab:pipeline"
        {pipeline_id, project, status, ref, sha, web_url, created_at,
         updated_at, duration, user}

    sourcetype="gitlab:job"
        {pipeline_id, job_id, name, stage, status, failure_reason,
         started_at, finished_at, duration, web_url, log_tail}

Logs are only attached to jobs whose status is in {failed, canceled} to keep
ingest volume manageable; the tail is the last `log_tail_lines` lines.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import gitlab
import gitlab.exceptions
import httpx

logger = logging.getLogger(__name__)

_DEFAULT_LOG_TAIL_LINES = 50
_DEFAULT_INDEX = "pipelineguard"
_BATCH_SIZE = 100
_HEC_TIMEOUT = 30.0
_RELATIVE_RE = re.compile(r"^-(\d+)([smhdw])$")
_RELATIVE_UNITS = {
    "s": "seconds",
    "m": "minutes",
    "h": "hours",
    "d": "days",
    "w": "weeks",
}


@dataclass
class IngestStats:
    pipelines: int = 0
    jobs: int = 0
    events_posted: int = 0
    hec_errors: int = 0


def parse_since(since: str) -> datetime:
    """Parse `-7d` / `-24h` / `2026-05-20T00:00:00Z` into a UTC datetime.

    Raises ValueError on unrecognized input.
    """
    m = _RELATIVE_RE.match(since.strip())
    if m:
        n, unit = int(m.group(1)), m.group(2)
        delta = timedelta(**{_RELATIVE_UNITS[unit]: n})
        return datetime.now(timezone.utc) - delta

    iso = since.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError as exc:
        raise ValueError(
            f"since={since!r} is not a recognized format. "
            "Use -7d / -24h / -30m or ISO8601 like 2026-05-20T00:00:00Z."
        ) from exc
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _to_epoch(value: Any) -> float | None:
    """Convert a GitLab ISO timestamp (or already-epoch) into epoch seconds."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except ValueError:
            return None
    return None


class GitLabToSplunkIngester:
    """Pump GitLab pipeline + job events into Splunk via HEC.

    Designed for hackathon-scale demos: pulls pipelines updated since a given
    point, enriches failed/canceled jobs with their log tail, and POSTs each
    pipeline and job as a separate HEC event so SPL can `stats` / `transaction`
    / `cluster` over them naturally.
    """

    def __init__(
        self,
        gitlab_token: str,
        gitlab_url: str = "https://gitlab.com",
        hec_url: str = "https://localhost:8088",
        hec_token: str = "",
        index: str = _DEFAULT_INDEX,
        verify_ssl: bool = True,
        log_tail_lines: int = _DEFAULT_LOG_TAIL_LINES,
    ) -> None:
        if not hec_token:
            raise ValueError("hec_token is required")
        self._gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)
        self._hec_collector_url = hec_url.rstrip("/") + "/services/collector/event"
        self._hec_headers = {
            "Authorization": f"Splunk {hec_token}",
            "Content-Type": "application/json",
        }
        self._index = index
        self._verify_ssl = verify_ssl
        self._log_tail_lines = log_tail_lines

    def ingest_project(
        self,
        project_path: str,
        since: str = "-7d",
        max_pipelines: int = 200,
    ) -> IngestStats:
        """Ingest pipelines (and their jobs) newer than `since`."""
        since_dt = parse_since(since)
        project = self._gl.projects.get(project_path)

        pipelines_iter = project.pipelines.list(
            updated_after=since_dt.isoformat(),
            order_by="updated_at",
            sort="desc",
            iterator=True,
        )

        events: list[dict[str, Any]] = []
        stats = IngestStats()

        for pipeline in pipelines_iter:
            if stats.pipelines >= max_pipelines:
                break

            events.append(self._pipeline_event(project_path, pipeline))
            stats.pipelines += 1

            try:
                jobs = pipeline.jobs.list(all=True)
            except gitlab.exceptions.GitlabListError as exc:
                logger.warning(
                    "Could not list jobs for pipeline %s: %s", pipeline.id, exc
                )
                jobs = []

            for job in jobs:
                events.append(self._job_event(project_path, pipeline, job, project))
                stats.jobs += 1

            if len(events) >= _BATCH_SIZE:
                stats.events_posted += self._post_batch(events, stats)
                events = []

        if events:
            stats.events_posted += self._post_batch(events, stats)

        return stats

    def _pipeline_event(self, project_path: str, pipeline: Any) -> dict[str, Any]:
        ts = _to_epoch(getattr(pipeline, "updated_at", None)) or _to_epoch(
            getattr(pipeline, "created_at", None)
        )
        return {
            "time": ts,
            "index": self._index,
            "sourcetype": "gitlab:pipeline",
            "event": {
                "pipeline_id": pipeline.id,
                "project": project_path,
                "status": pipeline.status,
                "ref": getattr(pipeline, "ref", ""),
                "sha": getattr(pipeline, "sha", ""),
                "web_url": getattr(pipeline, "web_url", ""),
                "created_at": getattr(pipeline, "created_at", None),
                "updated_at": getattr(pipeline, "updated_at", None),
                "duration": getattr(pipeline, "duration", None),
                "user": (getattr(pipeline, "user", {}) or {}).get("username"),
            },
        }

    def _job_event(
        self,
        project_path: str,
        pipeline: Any,
        job: Any,
        project: Any,
    ) -> dict[str, Any]:
        ts = (
            _to_epoch(getattr(job, "finished_at", None))
            or _to_epoch(getattr(job, "started_at", None))
            or _to_epoch(getattr(job, "created_at", None))
        )
        log_tail = ""
        if job.status in ("failed", "canceled"):
            log_tail = self._fetch_log_tail(project, job)
        return {
            "time": ts,
            "index": self._index,
            "sourcetype": "gitlab:job",
            "event": {
                "pipeline_id": pipeline.id,
                "job_id": job.id,
                "project": project_path,
                "name": job.name,
                "stage": getattr(job, "stage", ""),
                "status": job.status,
                "failure_reason": getattr(job, "failure_reason", None),
                "started_at": getattr(job, "started_at", None),
                "finished_at": getattr(job, "finished_at", None),
                "duration": getattr(job, "duration", None),
                "web_url": getattr(job, "web_url", ""),
                "log_tail": log_tail,
            },
        }

    def _fetch_log_tail(self, project: Any, job: Any) -> str:
        try:
            raw = project.jobs.get(job.id).trace()
        except gitlab.exceptions.GitlabGetError:
            return ""
        text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        lines = text.splitlines()
        if len(lines) <= self._log_tail_lines:
            return text
        return "\n".join(lines[-self._log_tail_lines :])

    def _post_batch(self, events: Iterable[dict[str, Any]], stats: IngestStats) -> int:
        body = "\n".join(json.dumps(e, default=str) for e in events)
        try:
            with httpx.Client(verify=self._verify_ssl, timeout=_HEC_TIMEOUT) as client:
                resp = client.post(
                    self._hec_collector_url,
                    headers=self._hec_headers,
                    content=body,
                )
            resp.raise_for_status()
            return len(body.splitlines())
        except httpx.HTTPError as exc:
            stats.hec_errors += 1
            logger.error("HEC POST failed: %s", exc)
            return 0
