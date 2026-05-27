"""GitLab webhook receiver — auto-diagnoses pipeline failures."""
from __future__ import annotations

import hmac
import logging
from typing import Any

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)

MAX_WEBHOOK_BODY_BYTES = 1_000_000  # GitLab payloads are <100 KB in practice

_LANDING_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>PipelineGuard — AI-powered GitLab CI diagnostics</title>
  <style>
    *{box-sizing:border-box;margin:0;padding:0}
    body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
         background:#0d1117;color:#e6edf3;min-height:100vh}
    header{background:linear-gradient(135deg,#1a1f2e 0%,#161b27 100%);
           border-bottom:1px solid #30363d;padding:2rem 2rem 1.5rem}
    header h1{font-size:2rem;font-weight:700;color:#58a6ff}
    header p{color:#8b949e;margin-top:.4rem;font-size:1.05rem}
    .badge{display:inline-block;background:#1f6feb;color:#fff;
           border-radius:4px;padding:.15rem .55rem;font-size:.78rem;
           font-weight:600;margin-left:.5rem;vertical-align:middle}
    main{max-width:900px;margin:0 auto;padding:2rem}
    .cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:1rem;margin:2rem 0}
    .card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.2rem}
    .card h3{color:#58a6ff;margin-bottom:.5rem;font-size:1rem}
    .card p{color:#8b949e;font-size:.9rem;line-height:1.5}
    .card .icon{font-size:1.6rem;margin-bottom:.5rem}
    section{margin:2rem 0}
    section h2{font-size:1.3rem;font-weight:600;color:#e6edf3;
               border-bottom:1px solid #30363d;padding-bottom:.5rem;margin-bottom:1rem}
    .demo-box{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1.5rem}
    label{display:block;color:#8b949e;font-size:.85rem;margin-bottom:.3rem}
    input{width:100%;background:#0d1117;border:1px solid #30363d;color:#e6edf3;
          border-radius:6px;padding:.55rem .75rem;font-size:.95rem;margin-bottom:1rem;
          outline:none;transition:border .2s}
    input:focus{border-color:#58a6ff}
    button{background:#238636;color:#fff;border:none;border-radius:6px;
           padding:.6rem 1.4rem;font-size:.95rem;cursor:pointer;font-weight:600;
           transition:background .2s}
    button:hover{background:#2ea043}
    button:disabled{background:#21262d;color:#484f58;cursor:not-allowed}
    pre{background:#0d1117;border:1px solid #30363d;border-radius:6px;
        padding:1rem;overflow-x:auto;font-size:.82rem;color:#e6edf3;
        white-space:pre-wrap;word-break:break-word;margin-top:1rem;display:none}
    .tag{display:inline-block;background:#21262d;border:1px solid #30363d;
         color:#8b949e;border-radius:12px;padding:.1rem .6rem;font-size:.78rem;
         margin:.15rem}
    .error{color:#f85149}
    .endpoint-row{display:flex;align-items:center;gap:.75rem;margin:.4rem 0}
    .method{background:#1f6feb;color:#fff;font-size:.75rem;font-weight:700;
            padding:.1rem .45rem;border-radius:3px;min-width:3.5rem;text-align:center}
    .method.post{background:#388bfd}
    code{background:#161b22;padding:.1rem .35rem;border-radius:3px;font-size:.85rem;color:#79c0ff}
    .arch{background:#0d1117;border:1px solid #30363d;border-radius:8px;padding:1rem;
          font-family:monospace;font-size:.82rem;line-height:1.6;color:#8b949e;overflow-x:auto}
    .arch .hi{color:#58a6ff}
  </style>
</head>
<body>
<header>
  <h1>&#x1F6E1; PipelineGuard <span class="badge">Gemini 2.0</span></h1>
  <p>AI-powered GitLab CI pipeline failure diagnostics &amp; auto-fix agent</p>
</header>
<main>

  <div class="cards">
    <div class="card">
      <div class="icon">&#x1F50D;</div>
      <h3>Instant Root-Cause Analysis</h3>
      <p>Gemini 2.0 Flash reads your pipeline logs and pinpoints the exact failure in seconds.</p>
    </div>
    <div class="card">
      <div class="icon">&#x1F527;</div>
      <h3>Concrete Fix Proposals</h3>
      <p>Returns diff-ready patches with high/medium/low confidence, ready to apply.</p>
    </div>
    <div class="card">
      <div class="icon">&#x1F4AC;</div>
      <h3>Auto MR Comments</h3>
      <p>Optionally posts the diagnosis directly on the failing merge request in GitLab.</p>
    </div>
    <div class="card">
      <div class="icon">&#x26A1;</div>
      <h3>Webhook Integration</h3>
      <p>Fires automatically on every pipeline failure — zero manual intervention required.</p>
    </div>
  </div>

  <section>
    <h2>Live Demo</h2>
    <div class="demo-box">
      <p style="color:#8b949e;font-size:.9rem;margin-bottom:1rem">
        Diagnose any failed GitLab pipeline. Enter a public project path and
        (optionally) a specific pipeline ID. The agent fetches logs and returns
        a root-cause analysis using Gemini 2.0 Flash. No comment will be posted.
      </p>
      <label for="proj">GitLab project (namespace/repo)</label>
      <input id="proj" placeholder="e.g. gitlab-org/gitlab-runner" />
      <label for="pid">Pipeline ID <span style="color:#484f58">(leave blank for latest failed)</span></label>
      <input id="pid" placeholder="optional" type="number" />
      <button id="runBtn" onclick="runDemo()">&#x25B6; Run Diagnosis</button>
      <pre id="out"></pre>
    </div>
  </section>

  <section>
    <h2>Architecture</h2>
    <div class="arch">
<span class="hi">GitLab Pipeline Fails</span>
       │
       ▼ webhook (X-Gitlab-Token validated)
<span class="hi">PipelineGuard / FastAPI</span>  ─────────────────────────────┐
       │                                                     │
       ▼ fetch logs + MR context                             ▼
<span class="hi">GitLab REST API</span>                                  <span class="hi">Gemini 2.0 Flash</span>
  (python-gitlab)                               (Vertex AI / AI Studio)
       │                                                     │
       └─────── structured DiagnosticReport ◄────────────────┘
                     │
                     ├─ root_cause  ─── posted as MR comment
                     ├─ fix_proposals (diff patches)
                     └─ failure_category (flaky / env / code / …)
    </div>
  </section>

  <section>
    <h2>API Endpoints</h2>
    <div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:1rem">
      <div class="endpoint-row">
        <span class="method">GET</span>
        <code>/</code>
        <span style="color:#8b949e;font-size:.88rem">This page</span>
      </div>
      <div class="endpoint-row">
        <span class="method">GET</span>
        <code>/health</code>
        <span style="color:#8b949e;font-size:.88rem">Health check → <code>{"status":"ok"}</code></span>
      </div>
      <div class="endpoint-row">
        <span class="method post">POST</span>
        <code>/demo</code>
        <span style="color:#8b949e;font-size:.88rem">Read-only diagnosis — body: <code>{"project":"org/repo","pipeline_id":123}</code></span>
      </div>
      <div class="endpoint-row">
        <span class="method post">POST</span>
        <code>/webhook/gitlab</code>
        <span style="color:#8b949e;font-size:.88rem">GitLab Pipeline webhook receiver (auto-diagnoses + comments)</span>
      </div>
      <div class="endpoint-row">
        <span class="method">GET</span>
        <code>/docs</code>
        <span style="color:#8b949e;font-size:.88rem">Interactive OpenAPI (Swagger UI)</span>
      </div>
    </div>
  </section>

  <section>
    <h2>Built With</h2>
    <div>
      <span class="tag">Gemini 2.0 Flash</span>
      <span class="tag">Vertex AI</span>
      <span class="tag">GitLab MCP Server</span>
      <span class="tag">FastAPI</span>
      <span class="tag">python-gitlab</span>
      <span class="tag">Google Cloud Run</span>
      <span class="tag">google-genai SDK</span>
    </div>
  </section>

</main>
<script>
async function runDemo() {
  const btn = document.getElementById('runBtn');
  const out = document.getElementById('out');
  const proj = document.getElementById('proj').value.trim();
  const pidVal = document.getElementById('pid').value.trim();
  if (!proj) { alert('Please enter a GitLab project path.'); return; }
  btn.disabled = true;
  btn.textContent = '⏳ Diagnosing…';
  out.style.display = 'block';
  out.textContent = 'Fetching pipeline logs and running Gemini analysis…\\n(this may take 15-30 seconds)';
  out.classList.remove('error');
  const body = { project: proj };
  if (pidVal) body.pipeline_id = parseInt(pidVal);
  try {
    const resp = await fetch('/demo', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(body)
    });
    const data = await resp.json();
    if (!resp.ok) {
      out.classList.add('error');
      out.textContent = 'Error ' + resp.status + ': ' + (data.detail || JSON.stringify(data));
    } else {
      out.textContent = JSON.stringify(data, null, 2);
    }
  } catch(e) {
    out.classList.add('error');
    out.textContent = 'Network error: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = '▶ Run Diagnosis';
  }
}
</script>
</body>
</html>"""


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
        from fastapi.responses import HTMLResponse
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

    @app.get("/", response_class=HTMLResponse)
    async def landing_page() -> str:
        return _LANDING_HTML

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "PipelineGuard"}

    @app.post("/demo")
    async def demo_diagnose(body: dict[str, Any]) -> dict[str, Any]:
        """Demo endpoint: diagnose a GitLab pipeline by project + pipeline_id.

        Body: {"project": "org/repo", "pipeline_id": 12345}
        The agent is read-only; it will NOT post a comment on the MR.
        """
        proj = body.get("project", "")
        pid = body.get("pipeline_id")
        if not proj:
            raise HTTPException(status_code=422, detail="project is required")
        pipeline_id: int | None = None
        if pid is not None:
            try:
                pipeline_id = int(pid)
            except (ValueError, TypeError):
                raise HTTPException(status_code=422, detail="pipeline_id must be an integer")
        try:
            report = await agent.diagnose(
                project=proj,
                pipeline_id=pipeline_id,
                post_comment=False,
            )
            return {
                "root_cause": report.root_cause,
                "category": report.failure_category.value if report.failure_category else "unknown",
                "is_flaky": report.is_flaky,
                "affected_jobs": report.affected_jobs,
                "fix_proposals": [
                    {
                        "file_path": f.file_path,
                        "description": f.description,
                        "confidence": f.confidence.value,
                        "diff": f.diff,
                    }
                    for f in (report.fix_proposals or [])
                ],
                "full_analysis": report.full_analysis,
            }
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc))

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
