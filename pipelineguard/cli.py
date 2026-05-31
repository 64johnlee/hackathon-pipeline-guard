"""PipelineGuard CLI — diagnose or watch GitLab CI pipelines."""
from __future__ import annotations

import asyncio
import logging
import sys

import click
from dotenv import load_dotenv
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.table import Table

from .agent import PipelineGuardAgent
from .splunk_agent import SplunkGuardAgent

load_dotenv()
console = Console()


@click.group()
@click.option("--debug", is_flag=True, default=False, help="Enable debug logging.")
def main(debug: bool) -> None:
    """PipelineGuard — AI-powered GitLab CI pipeline diagnostics."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)


@main.command()
@click.argument("project")
@click.option("--pipeline", "-p", type=int, default=None, metavar="ID",
              help="Specific pipeline ID (default: latest failed).")
@click.option("--comment/--no-comment", default=False,
              help="Post diagnostic comment on the associated MR.")
@click.option("--direct", is_flag=True, default=False,
              help="Skip GitLab MCP server, use python-gitlab directly.")
@click.option("--gemini-key", envvar="GEMINI_API_KEY", default="",
              help="Gemini API key ($GEMINI_API_KEY). Not needed when --vertex is set.")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True,
              help="GitLab PAT with api + read_repository scopes ($GITLAB_TOKEN).")
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com",
              show_default=True, help="GitLab base URL.")
@click.option("--vertex", "use_vertex", is_flag=True, default=False,
              help="Use Vertex AI (Google Cloud Agent Builder) instead of AI Studio.")
@click.option("--gcp-project", envvar="GCP_PROJECT", default="",
              help="GCP project ID for Vertex AI ($GCP_PROJECT).")
@click.option("--gcp-location", envvar="GCP_LOCATION", default="us-central1",
              show_default=True, help="Vertex AI region ($GCP_LOCATION).")
def diagnose(
    project: str,
    pipeline: int | None,
    comment: bool,
    direct: bool,
    gemini_key: str,
    gitlab_token: str,
    gitlab_url: str,
    use_vertex: bool,
    gcp_project: str,
    gcp_location: str,
) -> None:
    """Diagnose the latest (or a specific) failed pipeline in PROJECT.

    PROJECT is a GitLab namespace/project path, e.g. myorg/myrepo.

    Auth: set GEMINI_API_KEY for AI Studio, or GCP_PROJECT + --vertex for
    Google Cloud Agent Builder (Vertex AI).
    """
    if use_vertex and not gcp_project:
        console.print("[bold red]Error:[/] --vertex requires --gcp-project / $GCP_PROJECT")
        sys.exit(1)
    if not use_vertex and not gemini_key:
        console.print("[bold red]Error:[/] GEMINI_API_KEY is required (or use --vertex + GCP_PROJECT)")
        sys.exit(1)

    agent = PipelineGuardAgent(
        gemini_api_key=gemini_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        force_direct=direct,
        use_vertex=use_vertex,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )

    try:
        report = asyncio.run(
            agent.diagnose(
                project=project,
                pipeline_id=pipeline,
                post_comment=comment,
            )
        )
    except ValueError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        sys.exit(1)

    # Summary panel
    status_color = "red" if not report.is_flaky else "yellow"
    console.print()
    console.print(
        Panel(
            f"[bold {status_color}]Root cause:[/] {report.root_cause}\n"
            f"[dim]Category:[/] {report.failure_category.value}"
            + (" · [yellow]FLAKY[/]" if report.is_flaky else "")
            + (f"\n[dim]Affected jobs:[/] {', '.join(report.affected_jobs)}" if report.affected_jobs else ""),
            title="[bold cyan]Diagnosis[/]",
            border_style="cyan",
        )
    )

    # Fix proposals table
    if report.fix_proposals:
        table = Table(title="Proposed Fixes", show_lines=True)
        table.add_column("File", style="cyan", no_wrap=True)
        table.add_column("Description")
        table.add_column("Confidence", justify="center")
        for fix in report.fix_proposals:
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(
                fix.confidence.value, "white"
            )
            table.add_row(
                fix.file_path,
                fix.description,
                f"[{conf_color}]{fix.confidence.value}[/]",
            )
        console.print(table)

        for fix in report.fix_proposals:
            if fix.diff:
                console.print(f"\n[cyan]{fix.file_path}[/] diff:")
                console.print(Markdown(f"```diff\n{fix.diff}\n```"))

    # Full analysis
    console.print("\n[bold]Full Analysis[/]")
    console.print(Markdown(report.full_analysis))

    if report.mr_comment_url:
        console.print(f"\n[green]Comment posted:[/] {report.mr_comment_url}")
    if report.pipeline_url:
        console.print(f"[dim]Pipeline:[/] {report.pipeline_url}")


@main.command()
@click.argument("project")
@click.option("--interval", "-i", default=60, type=int, show_default=True,
              help="Poll interval in seconds.")
@click.option("--comment/--no-comment", default=True,
              help="Auto-post diagnostic comments on detected failures.")
@click.option("--direct", is_flag=True, default=False)
@click.option("--gemini-key", envvar="GEMINI_API_KEY", required=True)
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True)
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com")
def watch(
    project: str,
    interval: int,
    comment: bool,
    direct: bool,
    gemini_key: str,
    gitlab_token: str,
    gitlab_url: str,
) -> None:
    """Watch PROJECT continuously and diagnose new failures as they appear."""
    agent = PipelineGuardAgent(
        gemini_api_key=gemini_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        force_direct=direct,
    )

    console.print(
        f"[bold cyan]PipelineGuard[/] watching [green]{project}[/] "
        f"every [yellow]{interval}s[/] · Ctrl-C to stop"
    )

    seen: set[int] = set()

    async def _poll() -> None:
        from .backends.direct import DirectBackend
        import anyio

        backend = DirectBackend(gitlab_token, gitlab_url)
        while True:
            try:
                data = await anyio.to_thread.run_sync(
                    lambda: backend.get_failed_pipeline_data(project)
                )
                pid = data["pipeline_id"]
                if pid not in seen:
                    seen.add(pid)
                    console.print(
                        f"[yellow]New failure detected:[/] pipeline #{pid} — diagnosing…"
                    )
                    report = await agent.diagnose(
                        project=project,
                        pipeline_id=pid,
                        post_comment=comment,
                    )
                    console.print(f"[green]Done:[/] {report.root_cause}")
            except ValueError:
                pass  # no failed pipelines yet
            except Exception as exc:
                console.print(f"[red]Poll error:[/] {exc}")
            await asyncio.sleep(interval)

    asyncio.run(_poll())


# ---------------------------------------------------------------------------
# Serve (webhook) command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--host", default="0.0.0.0", show_default=True, help="Bind host.")
@click.option("--port", "-p", default=8765, type=int, show_default=True, help="Bind port.")
@click.option("--webhook-secret", envvar="WEBHOOK_SECRET", default="",
              help="Optional GitLab webhook token ($WEBHOOK_SECRET).")
@click.option("--comment/--no-comment", default=True,
              help="Auto-post diagnosis comment on the failing MR.")
@click.option("--direct", is_flag=True, default=False)
@click.option("--gemini-key", envvar="GEMINI_API_KEY", default="",
              help="Gemini API key ($GEMINI_API_KEY). Not needed when --vertex is set.")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True)
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com")
@click.option("--vertex", "use_vertex", is_flag=True, default=False,
              help="Use Vertex AI (Google Cloud Agent Builder) instead of AI Studio.")
@click.option("--gcp-project", envvar="GCP_PROJECT", default="",
              help="GCP project ID for Vertex AI ($GCP_PROJECT).")
@click.option("--gcp-location", envvar="GCP_LOCATION", default="us-central1",
              show_default=True, help="Vertex AI region ($GCP_LOCATION).")
def serve(
    host: str,
    port: int,
    webhook_secret: str,
    comment: bool,
    direct: bool,
    gemini_key: str,
    gitlab_token: str,
    gitlab_url: str,
    use_vertex: bool,
    gcp_project: str,
    gcp_location: str,
) -> None:
    """Start a webhook server to auto-diagnose GitLab pipeline failures.

    Configure a GitLab Pipeline webhook pointing to
    http://<host>:<port>/webhook/gitlab.
    When a pipeline fails PipelineGuard diagnoses it and posts a comment
    on the associated merge request.

    On Cloud Run, PORT env var is used automatically as the bind port.
    Auth: GEMINI_API_KEY for AI Studio, or GCP_PROJECT + --vertex for Vertex AI.
    """
    if use_vertex and not gcp_project:
        console.print("[bold red]Error:[/] --vertex requires --gcp-project / $GCP_PROJECT")
        sys.exit(1)
    if not use_vertex and not gemini_key:
        console.print("[bold red]Error:[/] GEMINI_API_KEY is required (or use --vertex + GCP_PROJECT)")
        sys.exit(1)

    try:
        import uvicorn
    except ImportError:
        console.print("[red]uvicorn is required:[/] pip install 'pipelineguard[web]'")
        sys.exit(1)

    from .webhook import make_app

    app = make_app(
        gemini_api_key=gemini_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        webhook_secret=webhook_secret,
        post_comment=comment,
        force_direct=direct,
        use_vertex=use_vertex,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )

    console.print(
        Panel(
            f"[bold cyan]PipelineGuard Webhook[/]\n"
            f"Endpoint: [green]http://{host}:{port}/webhook/gitlab[/]\n"
            f"Backend: [yellow]{'Vertex AI' if use_vertex else 'AI Studio'}[/]  "
            f"Post comment: [yellow]{'yes' if comment else 'no'}[/]",
            border_style="cyan",
        )
    )
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ---------------------------------------------------------------------------
# Deploy to Vertex AI Agent Engine (Google Cloud Agent Builder)
# ---------------------------------------------------------------------------

@main.command()
@click.option("--gcp-project", envvar="GCP_PROJECT", required=True,
              help="GCP project ID ($GCP_PROJECT).")
@click.option("--gcp-location", envvar="GCP_LOCATION", default="us-central1",
              show_default=True, help="Vertex AI region ($GCP_LOCATION).")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True,
              help="GitLab PAT baked into the deployed engine ($GITLAB_TOKEN).")
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com",
              show_default=True)
@click.option("--display-name", default="PipelineGuard", show_default=True,
              help="Display name for the Reasoning Engine resource.")
def deploy(
    gcp_project: str,
    gcp_location: str,
    gitlab_token: str,
    gitlab_url: str,
    display_name: str,
) -> None:
    """Deploy PipelineGuard to Vertex AI Agent Engine (Google Cloud Agent Builder).

    Requires: pip install 'pipelineguard[vertex]'
    Also requires Application Default Credentials: gcloud auth application-default login
    """
    try:
        import vertexai
        from vertexai.preview import reasoning_engines
    except ImportError:
        console.print(
            "[red]Vertex AI SDK not found.[/] Install with:\n"
            "  pip install 'pipelineguard[vertex]'"
        )
        sys.exit(1)

    from .vertex_agent import PipelineGuardVertexApp

    console.print(
        Panel(
            f"[bold cyan]Deploying PipelineGuard[/] to Vertex AI Agent Engine\n"
            f"Project: [green]{gcp_project}[/]  Location: [yellow]{gcp_location}[/]",
            border_style="cyan",
        )
    )

    vertexai.init(project=gcp_project, location=gcp_location)

    app = PipelineGuardVertexApp(
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        gcp_project=gcp_project,
        gcp_location=gcp_location,
    )

    console.print("[dim]Creating Reasoning Engine (this takes ~2 min)…[/]")
    remote_app = reasoning_engines.ReasoningEngine.create(
        app,
        requirements=[
            "pipelineguard[web]>=0.1.0",
            "google-cloud-aiplatform[reasoningengine]>=1.60.0",
        ],
        display_name=display_name,
        description="AI-powered GitLab CI pipeline diagnostics using Gemini 2.5 Flash",
    )

    resource_name = remote_app.resource_name
    console.print(
        Panel(
            f"[bold green]Deployed![/]\n"
            f"Resource: [cyan]{resource_name}[/]\n\n"
            f"Query it:\n"
            f"  from vertexai.preview import reasoning_engines\n"
            f"  app = reasoning_engines.ReasoningEngine('{resource_name}')\n"
            f"  app.query(project='myorg/myrepo')",
            title="[bold cyan]Agent Engine[/]",
            border_style="green",
        )
    )


# ---------------------------------------------------------------------------
# Splunk subcommand group
# ---------------------------------------------------------------------------

@main.group()
def splunk() -> None:
    """SplunkGuard — AI-powered Splunk observability investigations."""


@splunk.command()
@click.argument("question")
@click.option("--earliest", "-e", default="-24h", show_default=True,
              help="Earliest time for Splunk searches (SPL time modifier).")
@click.option("--latest", "-l", default="now", show_default=True,
              help="Latest time for Splunk searches.")
@click.option("--splunk-url", envvar="SPLUNK_MCP_URL",
              default="https://localhost:8089/services/mcp", show_default=True,
              help="Splunk MCP Server endpoint ($SPLUNK_MCP_URL).")
@click.option("--splunk-token", envvar="SPLUNK_MCP_TOKEN", required=True,
              help="Encrypted token from Splunk MCP Server App ($SPLUNK_MCP_TOKEN).")
@click.option("--no-verify-ssl", is_flag=True, default=False,
              help="Disable SSL verification (for local Splunk with self-signed cert).")
@click.option("--direct", is_flag=True, default=False,
              help="Skip MCP server, query Splunk REST API directly.")
@click.option("--gemini-key", envvar="GEMINI_API_KEY", required=True,
              help="Gemini API key ($GEMINI_API_KEY).")
def investigate(
    question: str,
    earliest: str,
    latest: str,
    splunk_url: str,
    splunk_token: str,
    no_verify_ssl: bool,
    direct: bool,
    gemini_key: str,
) -> None:
    """Investigate a question against Splunk data using Gemini.

    QUESTION is a natural-language description of what to investigate,
    e.g. "why did build error rates spike at 2am?" or "find failed logins".
    """
    agent = SplunkGuardAgent(
        gemini_api_key=gemini_key,
        splunk_token=splunk_token,
        splunk_url=splunk_url,
        verify_ssl=not no_verify_ssl,
        force_direct=direct,
    )

    try:
        report = asyncio.run(
            agent.investigate(question=question, earliest=earliest, latest=latest)
        )
    except Exception as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        sys.exit(1)

    console.print()
    ongoing_tag = " · [yellow]ONGOING[/]" if report.is_ongoing else ""
    console.print(
        Panel(
            f"[bold red]Root cause:[/] {report.root_cause}\n"
            f"[dim]Category:[/] {report.investigation_category}"
            + ongoing_tag
            + (f"\n[dim]Affected:[/] {', '.join(report.affected_components)}" if report.affected_components else "")
            + (f"\n[dim]Time range:[/] {report.time_range}" if report.time_range else ""),
            title="[bold cyan]Investigation[/]",
            border_style="cyan",
        )
    )

    if report.recommended_actions:
        table = Table(title="Recommended Actions", show_lines=True)
        table.add_column("Action", style="cyan")
        table.add_column("Confidence", justify="center")
        table.add_column("Monitor SPL")
        for action in report.recommended_actions:
            conf = action.get("confidence", "")
            conf_color = {"high": "green", "medium": "yellow", "low": "red"}.get(conf, "white")
            table.add_row(
                action.get("action", ""),
                f"[{conf_color}]{conf}[/]",
                action.get("spl_query", ""),
            )
        console.print(table)

    console.print("\n[bold]Full Analysis[/]")
    console.print(Markdown(report.full_analysis))


@splunk.command()
@click.argument("project")
@click.option("--since", default="-7d", show_default=True,
              help="Ingest pipelines updated since this point "
                   "(`-7d`, `-24h`, or ISO8601 like 2026-05-20T00:00:00Z).")
@click.option("--max-pipelines", default=200, type=int, show_default=True,
              help="Hard cap on pipelines to ingest in one run.")
@click.option("--hec-url", envvar="SPLUNK_HEC_URL",
              default="https://localhost:8088", show_default=True,
              help="Splunk HEC base URL ($SPLUNK_HEC_URL).")
@click.option("--hec-token", envvar="SPLUNK_HEC_TOKEN", required=True,
              help="Splunk HEC token ($SPLUNK_HEC_TOKEN).")
@click.option("--index", default="pipelineguard", show_default=True,
              help="Splunk index to write into.")
@click.option("--no-verify-ssl", is_flag=True, default=False,
              help="Disable SSL verification (for local Splunk with self-signed cert).")
@click.option("--log-tail-lines", default=50, type=int, show_default=True,
              help="Lines of failed-job log tail to attach to each job event.")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True,
              help="GitLab PAT with api + read_repository scopes ($GITLAB_TOKEN).")
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com",
              show_default=True, help="GitLab base URL.")
def ingest(
    project: str,
    since: str,
    max_pipelines: int,
    hec_url: str,
    hec_token: str,
    index: str,
    no_verify_ssl: bool,
    log_tail_lines: int,
    gitlab_token: str,
    gitlab_url: str,
) -> None:
    """Ingest GitLab pipeline + job events for PROJECT into Splunk via HEC.

    PROJECT is a GitLab namespace/project path, e.g. myorg/myrepo.

    After ingest, query in Splunk:
        index=pipelineguard sourcetype="gitlab:job" status=failed
        | stats count by stage, name
    """
    from rich.progress import Progress, SpinnerColumn, TextColumn

    from .ingesters import GitLabToSplunkIngester

    ingester = GitLabToSplunkIngester(
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        hec_url=hec_url,
        hec_token=hec_token,
        index=index,
        verify_ssl=not no_verify_ssl,
        log_tail_lines=log_tail_lines,
    )

    console.print(
        Panel(
            f"[bold cyan]GitLab → Splunk[/]\n"
            f"Project: [green]{project}[/]  Since: [yellow]{since}[/]\n"
            f"HEC: [yellow]{hec_url}[/]  Index: [yellow]{index}[/]",
            border_style="cyan",
        )
    )

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Ingesting…", total=None)
            stats = ingester.ingest_project(
                project_path=project,
                since=since,
                max_pipelines=max_pipelines,
            )
            progress.update(task, description="Done")
    except ValueError as exc:
        console.print(f"[bold red]Error:[/] {exc}")
        sys.exit(1)

    table = Table(title="Ingest summary", show_lines=False)
    table.add_column("Metric", style="cyan")
    table.add_column("Count", justify="right")
    table.add_row("Pipelines", str(stats.pipelines))
    table.add_row("Jobs", str(stats.jobs))
    table.add_row("Events posted to HEC", str(stats.events_posted))
    if stats.hec_errors:
        table.add_row("[red]HEC errors[/]", f"[red]{stats.hec_errors}[/]")
    console.print(table)

    if stats.hec_errors:
        sys.exit(1)
