"""GitLab webhook receiver — auto-diagnoses pipeline failures."""
from __future__ import annotations

import hmac
import logging
from typing import Any

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)



MAX_WEBHOOK_BODY_BYTES = 1_000_000  # GitLab payloads are <100 KB in practice


async def handle_pipeline_event(
    payload: dict[str, Any],
    agent: Any,
    post_comment: bool = True,
) -> dict[str, str]:
    """
    Process a GitLab pipeline webhook event.

    Returns a status dict.  status="error" signals a diagnostic failure;
    callers that speak HTTP should translate this to a 5xx response so
    GitLab retries the delivery.
    """
    kind = payload.get("object_kind")
    if kind != "pipeline":
        return {"status": "ignored", "reason": f"event kind={kind!r}"}

    attrs = payload.get("object_attributes", {})
    status = attrs.get("status", "")
    if status != "failed":
        return {"status": "ignored", "reason": f"pipeline status={status!r}"}

    pipeline_id = attrs.get("id")
    if not isinstance(pipeline_id, int):
        return {"status": "error", "reason": f"invalid object_attributes.id: {pipeline_id!r}"}

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
        failure_category = getattr(report, "failure_category", None)
        result: dict[str, str] = {
            "status": "diagnosed",
            "project": project,
            "pipeline_id": str(pipeline_id),
            "root_cause": getattr(report, "root_cause", "unknown"),
            "category": failure_category.value if failure_category is not None else "unknown",
        }
        mr_comment_url = getattr(report, "mr_comment_url", None)
        if mr_comment_url:
            result["comment_url"] = mr_comment_url
        console.print(f"[green]Done:[/] {result['root_cause']}")
        return result
    except Exception as exc:
        logger.exception("Diagnosis failed for pipeline #%s", pipeline_id)
        return {"status": "error", "reason": str(exc)}


def make_app(
    gemini_api_key: str = "",
    gitlab_token: str = "",
    gitlab_url: str = "https://gitlab.com",
    webhook_secret: str = "",
    post_comment: bool = True,
    force_direct: bool = False,
    use_vertex: bool = False,
    gcp_project: str = "",
    gcp_location: str = "us-central1",
) -> Any:
    """
    Build and return a FastAPI application for receiving GitLab webhooks.

    Requires: pip install fastapi uvicorn
    """
    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:
        raise ImportError(
            "FastAPI is required for the webhook server. "
            "Install it with: pip install 'pipelineguard[web]'"
        ) from exc

    from .agent import PipelineGuardAgent

    if not webhook_secret:
        logger.warning(
            "WEBHOOK_SECRET is not set — /webhook/gitlab accepts requests from any source. "
            "Set WEBHOOK_SECRET (or $WEBHOOK_SECRET env var) to restrict access."
        )
        console.print(
            "[yellow]Warning:[/] No WEBHOOK_SECRET set — webhook endpoint is unauthenticated."
        )

    agent = PipelineGuardAgent(
        gemini_api_key=gemini_api_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        force_direct=force_direct,
        use_vertex=use_vertex,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )

    app = FastAPI(
        title="PipelineGuard Webhook",
        description="Auto-diagnoses GitLab CI pipeline failures using Gemini.",
        version="0.1.0",
    )

    # Add middleware to validate webhook token if secret is configured
    if webhook_secret:
        from starlette.middleware.base import BaseHTTPMiddleware
        from starlette.requests import Request as StarletteRequest
        from starlette.responses import JSONResponse

        class GitLabTokenMiddleware(BaseHTTPMiddleware):
            async def dispatch(self, request: StarletteRequest, call_next):
                if request.url.path == "/webhook/gitlab" and request.method == "POST":
                    token_header = request.headers.get("X-Gitlab-Token", "")
                    if not hmac.compare_digest(webhook_secret.encode(), token_header.encode()):
                        return JSONResponse(
                            {"detail": "Invalid webhook token"}, status_code=401
                        )
                return await call_next(request)

        app.add_middleware(GitLabTokenMiddleware)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "PipelineGuard"}

    @app.post("/webhook/gitlab")
    async def gitlab_webhook(payload: dict[str, Any]) -> dict[str, str]:
        # X-Gitlab-Token validation is handled by GitLabTokenMiddleware (if WEBHOOK_SECRET is set).
        # This avoids FastAPI 422 parameter binding issues with the Request object.

        result = await handle_pipeline_event(payload, agent, post_comment=post_comment)

        # Translate diagnostic errors to 500 so GitLab retries the delivery.
        if result.get("status") == "error":
            raise HTTPException(
                status_code=500, detail=result.get("reason", "Diagnosis failed")
            )

        return result

    return app
