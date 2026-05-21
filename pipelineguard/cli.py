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
@click.option("--gemini-key", envvar="GEMINI_API_KEY", required=True,
              help="Gemini API key ($GEMINI_API_KEY).")
@click.option("--gitlab-token", envvar="GITLAB_TOKEN", required=True,
              help="GitLab PAT with api + read_repository scopes ($GITLAB_TOKEN).")
@click.option("--gitlab-url", envvar="GITLAB_URL", default="https://gitlab.com",
              show_default=True, help="GitLab base URL.")
def diagnose(
    project: str,
    pipeline: int | None,
    comment: bool,
    direct: bool,
    gemini_key: str,
    gitlab_token: str,
    gitlab_url: str,
) -> None:
    """Diagnose the latest (or a specific) failed pipeline in PROJECT.

    PROJECT is a GitLab namespace/project path, e.g. myorg/myrepo.
    """
    agent = PipelineGuardAgent(
        gemini_api_key=gemini_key,
        gitlab_token=gitlab_token,
        gitlab_url=gitlab_url,
        force_direct=direct,
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
