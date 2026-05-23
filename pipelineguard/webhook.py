"""GitLab webhook receiver — auto-diagnoses pipeline failures."""
from __future__ import annotations

import hmac
import logging
from typing import Any

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


async def handle_pipeline_event(
    payload: dict[str, Any],
    agent: Any,
    post_comment: bool = True,
) -> dict[str, str]:
    """
    Process a GitLab pipeline webhook event.

    Returns a status dict suitable for use as an HTTP response body.
    """
    kind = payload.get("object_kind")
    if kind != "pipeline":
        return {"status": "ignored", "reason": f"event kind={kind!r}"}

    attrs = payload.get("object_attributes", {})
    status = attrs.get("status", "")
    if status != "failed":
        return {"status": "ignored", "reason": f"pipeline status={status!r}"}

    pipeline_id = attrs.get("id")
    if not pipeline_id:
        return {"status": "error", "reason": "missing object_attributes.id"}
    project: str = payload.get("project", {}).get("path_with_namespace", "")
    if not project:
        return {"status": "error", "reason": "missing project.path_with_namespace"}

    console.print(
        f"[cyan]Webhook:[/] pipeline #{pipeline_id} failed in [green]{project}[/] — diagnosing…"
    )

    try:
        report = await agent.diagnose(
            project=project,
            pipeline_id=pipeline_id,
            post_comment=post_comment,
        )
        result: dict[str, str] = {
            "status": "diagnosed",
            "project": project,
            "pipeline_id": str(pipeline_id),
            "root_cause": report.root_cause,
            "category": report.failure_category.value,
        }
        if report.mr_comment_url:
            result["comment_url"] = report.mr_comment_url
        console.print(f"[green]Done:[/] {report.root_cause}")
        return result
    except Exception as exc:
        logger.exception("Diagnosis failed for pipeline #%d", pipeline_id)
        return {"status": "error", "reason": str(exc)}


def make_app(
    gemini_api_key: str,
    gitlab_token: str,
    gitlab_url: str = "https://gitlab.com",
    webhook_secret: str = "",
    post_comment: bool = True,
    force_direct: bool = False,
) -> Any:
    """
    Build and return a FastAPI application for receiving GitLab webhooks.

    Requires: pip install fastapi uvicorn
    """
    try:
        from fastapi import FastAPI, HTTPException, Request
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the webhook server. "
            "Install it with: pip install 'pipelineguard[web]'"
        ) from exc

    from .agent import PipelineGuardAgent

    agent = PipelineGuardAgent(
        gemini_api_key=gemini_api_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        force_direct=force_direct,
    )

    app = FastAPI(
        title="PipelineGuard Webhook",
        description="Auto-diagnoses GitLab CI pipeline failures using Gemini.",
        version="0.1.0",
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "PipelineGuard"}

    @app.post("/webhook/gitlab")
    async def gitlab_webhook(request: Request) -> dict[str, str]:
        body = await request.body()
        token_header = request.headers.get("X-Gitlab-Token", "")

        if webhook_secret and not hmac.compare_digest(
            webhook_secret.encode(), token_header.encode()
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook token")

        try:
            import json
            payload = json.loads(body)
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid JSON payload")

        return await handle_pipeline_event(payload, agent, post_comment=post_comment)

    return app
