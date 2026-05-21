"""Direct python-gitlab backend — no MCP server required."""
from __future__ import annotations

import logging
from typing import Any

import gitlab
import gitlab.exceptions

logger = logging.getLogger(__name__)

_LOG_TAIL_LINES = 400  # lines to keep from end of each job log


class DirectBackend:
    """Fetches GitLab pipeline data using the python-gitlab library directly."""

    def __init__(self, gitlab_token: str, gitlab_url: str = "https://gitlab.com") -> None:
        self._gl = gitlab.Gitlab(gitlab_url, private_token=gitlab_token)

    def get_failed_pipeline_data(
        self, project_path: str, pipeline_id: int | None = None
    ) -> dict[str, Any]:
        """Return a dict with pipeline metadata and job logs for all failed jobs."""
        project = self._gl.projects.get(project_path)

        if pipeline_id is not None:
            pipeline = project.pipelines.get(pipeline_id)
        else:
            failed = project.pipelines.list(
                status="failed", per_page=1, order_by="id", sort="desc"
            )
            if not failed:
                raise ValueError(f"No failed pipelines found in {project_path!r}")
            pipeline = failed[0]

        all_jobs = pipeline.jobs.list(all=True)
        failed_jobs = [j for j in all_jobs if j.status in ("failed", "canceled")]

        job_data: list[dict[str, Any]] = []
        for job in failed_jobs:
            try:
                raw_log = project.jobs.get(job.id).trace()
                if isinstance(raw_log, bytes):
                    log_text = raw_log.decode("utf-8", errors="replace")
                else:
                    log_text = str(raw_log)
            except gitlab.exceptions.GitlabGetError:
                log_text = "(log unavailable)"

            lines = log_text.splitlines()
            tail = "\n".join(lines[-_LOG_TAIL_LINES:]) if len(lines) > _LOG_TAIL_LINES else log_text

            job_data.append(
                {
                    "name": job.name,
                    "stage": getattr(job, "stage", ""),
                    "status": job.status,
                    "failure_reason": getattr(job, "failure_reason", None),
                    "log_tail": tail,
                    "web_url": getattr(job, "web_url", ""),
                }
            )

        return {
            "project": project_path,
            "pipeline_id": pipeline.id,
            "pipeline_url": getattr(pipeline, "web_url", ""),
            "pipeline_status": pipeline.status,
            "ref": getattr(pipeline, "ref", ""),
            "sha": getattr(pipeline, "sha", ""),
            "failed_jobs": job_data,
        }

    def post_pipeline_comment(
        self, project_path: str, pipeline_sha: str, comment: str
    ) -> str:
        """Post a note on the MR associated with pipeline_sha, or return '' if none."""
        project = self._gl.projects.get(project_path)
        mrs = project.mergerequests.list(
            state="opened", per_page=20, order_by="updated_at"
        )
        for mr in mrs:
            if getattr(mr, "sha", None) == pipeline_sha:
                note = mr.notes.create({"body": comment})
                return f"{mr.web_url}#note_{note.id}"

        logger.debug("No open MR matching sha=%s; skipping comment", pipeline_sha[:8])
        return ""

    def get_file_content(self, project_path: str, file_path: str, ref: str = "HEAD") -> str:
        """Return the raw content of a file at a given ref."""
        project = self._gl.projects.get(project_path)
        try:
            f = project.files.get(file_path=file_path, ref=ref)
            return f.decode().decode("utf-8", errors="replace")
        except gitlab.exceptions.GitlabGetError:
            return ""
