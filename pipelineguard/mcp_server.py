"""PipelineGuard MCP server — stdio MCP interface to GitLab pipeline data.

Exposes the GitLab operations the PipelineGuard agent needs, as MCP tools.

Run standalone:
    GITLAB_PERSONAL_ACCESS_TOKEN=glpat-... python -m pipelineguard.mcp_server

Or via the console script:
    GITLAB_PERSONAL_ACCESS_TOKEN=glpat-... pipelineguard-mcp

Configuration (env vars):
    GITLAB_PERSONAL_ACCESS_TOKEN  GitLab PAT with api + read_repository scopes
    GITLAB_TOKEN                  Fallback name for the PAT (compatibility)
    GITLAB_URL                    GitLab base URL (default: https://gitlab.com)
"""
from __future__ import annotations

import json
import logging
import os
from typing import Any

import gitlab
import gitlab.exceptions
from mcp.server.fastmcp import FastMCP

logger = logging.getLogger("pipelineguard.mcp_server")

_DEFAULT_LOG_TAIL = 400


def _get_client() -> gitlab.Gitlab:
    token = (
        os.environ.get("GITLAB_PERSONAL_ACCESS_TOKEN")
        or os.environ.get("GITLAB_TOKEN")
        or ""
    )
    if not token:
        raise RuntimeError(
            "GITLAB_PERSONAL_ACCESS_TOKEN (or GITLAB_TOKEN) env var is required"
        )
    url = os.environ.get("GITLAB_URL", "https://gitlab.com")
    return gitlab.Gitlab(url, private_token=token)


mcp = FastMCP("pipelineguard-mcp")


@mcp.tool()
def list_pipelines(
    project_id: str,
    status: str = "",
    per_page: int = 10,
) -> str:
    """List recent pipelines for a GitLab project.

    Args:
        project_id: GitLab project path (e.g. "gitlab-org/gitlab") or numeric ID.
        status: Optional status filter ("failed", "success", "running", "canceled", "skipped").
        per_page: Max pipelines to return (default 10, max 100).

    Returns JSON: list of {id, status, ref, sha, web_url, created_at, updated_at}.
    """
    gl = _get_client()
    project = gl.projects.get(project_id)
    kwargs: dict[str, Any] = {
        "per_page": max(1, min(per_page, 100)),
        "order_by": "id",
        "sort": "desc",
    }
    if status:
        kwargs["status"] = status
    pipelines = project.pipelines.list(**kwargs)
    out = [
        {
            "id": p.id,
            "status": p.status,
            "ref": getattr(p, "ref", ""),
            "sha": getattr(p, "sha", ""),
            "web_url": getattr(p, "web_url", ""),
            "created_at": getattr(p, "created_at", ""),
            "updated_at": getattr(p, "updated_at", ""),
        }
        for p in pipelines
    ]
    return json.dumps(out)


@mcp.tool()
def get_pipeline_jobs(project_id: str, pipeline_id: int) -> str:
    """List all jobs in a pipeline.

    Args:
        project_id: GitLab project path or numeric ID.
        pipeline_id: Numeric pipeline ID.

    Returns JSON: list of {id, name, stage, status, failure_reason, web_url}.
    """
    gl = _get_client()
    project = gl.projects.get(project_id)
    pipeline = project.pipelines.get(pipeline_id)
    jobs = pipeline.jobs.list(all=True)
    out = [
        {
            "id": j.id,
            "name": j.name,
            "stage": getattr(j, "stage", ""),
            "status": j.status,
            "failure_reason": getattr(j, "failure_reason", None),
            "web_url": getattr(j, "web_url", ""),
        }
        for j in jobs
    ]
    return json.dumps(out)


@mcp.tool()
def get_job_log(
    project_id: str,
    job_id: int,
    tail_lines: int = _DEFAULT_LOG_TAIL,
) -> str:
    """Fetch the log (trace) of a GitLab CI job, optionally tail-limited.

    Args:
        project_id: GitLab project path or numeric ID.
        job_id: Numeric job ID.
        tail_lines: Return only the last N lines (default 400). Pass 0 for the full log.

    Returns the log text directly. Large logs are tail-truncated to fit LLM context.
    """
    gl = _get_client()
    project = gl.projects.get(project_id)
    try:
        raw = project.jobs.get(job_id).trace()
    except gitlab.exceptions.GitlabGetError:
        return "(log unavailable)"
    text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
    if tail_lines <= 0:
        return text
    lines = text.splitlines()
    if len(lines) <= tail_lines:
        return text
    return "\n".join(lines[-tail_lines:])


@mcp.tool()
def find_merge_request_by_sha(project_id: str, sha: str) -> str:
    """Find the open merge request whose head commit matches a SHA.

    Args:
        project_id: GitLab project path or numeric ID.
        sha: Full commit SHA from a pipeline.

    Returns JSON: {iid, web_url, title} of the matching MR, or {} if none.
    """
    gl = _get_client()
    project = gl.projects.get(project_id)
    mrs = project.mergerequests.list(state="opened", per_page=50, order_by="updated_at")
    for mr in mrs:
        if getattr(mr, "sha", None) == sha:
            return json.dumps(
                {
                    "iid": mr.iid,
                    "web_url": mr.web_url,
                    "title": getattr(mr, "title", ""),
                }
            )
    return json.dumps({})


@mcp.tool()
def create_merge_request_note(
    project_id: str,
    merge_request_iid: int,
    body: str,
) -> str:
    """Post a comment (note) on a merge request.

    Args:
        project_id: GitLab project path or numeric ID.
        merge_request_iid: MR internal ID (the "!42" number, not the global id).
        body: Markdown comment body.

    Returns JSON: {note_id, web_url} of the created note.
    """
    gl = _get_client()
    project = gl.projects.get(project_id)
    mr = project.mergerequests.get(merge_request_iid)
    note = mr.notes.create({"body": body})
    return json.dumps(
        {
            "note_id": note.id,
            "web_url": f"{mr.web_url}#note_{note.id}",
        }
    )


def main() -> None:
    logging.basicConfig(level=logging.WARNING)
    mcp.run()


if __name__ == "__main__":
    main()
