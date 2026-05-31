"""Core PipelineGuard agent — orchestrates Gemini + GitLab backends."""
from __future__ import annotations

import json
import logging
from typing import Any

import anyio
from google import genai
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .backends.direct import DirectBackend
from .backends.gitlab_mcp import GitLabOfficialMCPBackend
from .backends.mcp import MCPBackend
from .models import Confidence, DiagnosisReport, FailureCategory, FixProposal
from .prompts import SYSTEM_PROMPT, build_analysis_prompt

logger = logging.getLogger(__name__)
console = Console()

_GEMINI_MODEL = "gemini-2.5-flash"
_MAX_TOOL_ITERATIONS = 15


class PipelineGuardAgent:
    """
    Diagnoses GitLab CI pipeline failures using Gemini 2.5 Flash.

    Primary mode: Gemini agentic loop with GitLab MCP server tools.
    Fallback mode: single-shot Gemini call with pre-fetched log data.

    Auth modes:
      - AI Studio: pass gemini_api_key (GEMINI_API_KEY env var)
      - Vertex AI / Agent Builder: pass gcp_project + gcp_location (no API key needed)
    """

    def __init__(
        self,
        gemini_api_key: str = "",
        gitlab_token: str = "",
        gitlab_url: str = "https://gitlab.com",
        force_direct: bool = False,
        # Vertex AI / Google Cloud Agent Builder
        use_vertex: bool = False,
        gcp_project: str = "",
        gcp_location: str = "us-central1",
    ) -> None:
        if use_vertex or (not gemini_api_key and gcp_project):
            self._genai = genai.Client(
                vertexai=True,
                project=gcp_project,
                location=gcp_location,
            )
        else:
            self._genai = genai.Client(api_key=gemini_api_key)
        self._gitlab_token = gitlab_token
        self._gitlab_url = gitlab_url
        self._use_mcp = (not force_direct) and MCPBackend.is_available()

    async def diagnose(
        self,
        project: str,
        pipeline_id: int | None = None,
        post_comment: bool = False,
        create_fix_mr: bool = False,
    ) -> DiagnosisReport:
        mode = "GitLab MCP (official) + PipelineGuard MCP" if self._use_mcp else "direct"
        console.print(
            Panel(
                f"[bold cyan]PipelineGuard[/] · project [green]{project}[/]"
                + (f" · pipeline [yellow]#{pipeline_id}[/]" if pipeline_id else " · latest failed")
                + f"\n[dim]mode: {mode}[/]",
                border_style="cyan",
            )
        )
        if self._use_mcp:
            return await self._diagnose_mcp(project, pipeline_id, post_comment)
        return await self._diagnose_direct(project, pipeline_id, post_comment)

    # ------------------------------------------------------------------
    # MCP mode — Gemini drives an agentic tool-call loop
    # ------------------------------------------------------------------

    async def _diagnose_mcp(
        self,
        project: str,
        pipeline_id: int | None,
        post_comment: bool,
    ) -> DiagnosisReport:
        async with MCPBackend(self._gitlab_token, self._gitlab_url) as pipeline_backend:
            async with GitLabOfficialMCPBackend(self._gitlab_token, self._gitlab_url) as official_backend:
                if official_backend.connected:
                    console.print(
                        "  [dim green]✓ Official GitLab MCP server connected[/]"
                    )
                else:
                    console.print(
                        "  [dim yellow]⚠ Official GitLab MCP server unavailable"
                        " — using pipeline MCP only[/]"
                    )

                # Merge tools: pipeline-specific tools first so Gemini
                # prefers them for diagnosis; official tools provide context.
                pipeline_tools = await pipeline_backend.list_tools_as_gemini()
                official_tools = await official_backend.list_tools_as_gemini()

                all_declarations = []
                for tool_obj in pipeline_tools + official_tools:
                    all_declarations.extend(tool_obj.function_declarations or [])
                # Guard: an empty function_declarations list causes a Gemini API error.
                # This should not occur (bundled MCP always starts), but be safe.
                merged_tools = (
                    [types.Tool(function_declarations=all_declarations)]
                    if all_declarations
                    else pipeline_tools  # last-resort fallback to pipeline-only tools
                )

                prompt = build_analysis_prompt(project=project, pipeline_id=pipeline_id)
                messages: list[types.Content] = [
                    types.Content(role="user", parts=[types.Part(text=prompt)])
                ]
                final_text = await self._run_tool_loop(
                    pipeline_backend, official_backend, merged_tools, messages
                )
        return _parse_report(final_text, project, pipeline_id)

    async def _run_tool_loop(
        self,
        pipeline_backend: MCPBackend,
        official_backend: GitLabOfficialMCPBackend,
        tools: list[types.Tool],
        messages: list[types.Content],
    ) -> str:
        final_text = ""
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task_id = progress.add_task("Thinking…", total=None)

            for iteration in range(1, _MAX_TOOL_ITERATIONS + 1):
                progress.update(task_id, description=f"Iteration {iteration}/{_MAX_TOOL_ITERATIONS}…")

                response = self._genai.models.generate_content(
                    model=_GEMINI_MODEL,
                    contents=messages,
                    config=types.GenerateContentConfig(
                        system_instruction=SYSTEM_PROMPT,
                        tools=tools,
                        temperature=0.1,
                    ),
                )

                if not response.candidates:
                    logger.warning("Gemini returned no candidates (content filtered?)")
                    break

                candidate = response.candidates[0]
                messages.append(candidate.content)

                tool_calls = [
                    p.function_call
                    for p in candidate.content.parts
                    if p.function_call
                ]
                text_parts = [
                    p.text
                    for p in candidate.content.parts
                    if p.text
                ]

                if text_parts:
                    final_text = "\n".join(text_parts)

                if not tool_calls:
                    break

                tool_responses: list[types.Part] = []
                for fc in tool_calls:
                    progress.update(task_id, description=f"→ {fc.name}(…)")
                    console.print(f"  [dim]→ {fc.name}({_fmt_args(dict(fc.args))})[/]")

                    # Route to the correct backend by tool name prefix.
                    if official_backend.owns_tool(fc.name):
                        result_text = await official_backend.call_tool(fc.name, dict(fc.args))
                    else:
                        result_text = await pipeline_backend.call_tool(fc.name, dict(fc.args))

                    tool_responses.append(
                        types.Part(
                            function_response=types.FunctionResponse(
                                name=fc.name,
                                response={"output": result_text},
                            )
                        )
                    )

                messages.append(types.Content(role="tool", parts=tool_responses))

        return final_text

    # ------------------------------------------------------------------
    # Direct mode — pre-fetch logs, single Gemini call
    # ------------------------------------------------------------------

    async def _diagnose_direct(
        self,
        project: str,
        pipeline_id: int | None,
        post_comment: bool,
    ) -> DiagnosisReport:
        backend = DirectBackend(self._gitlab_token, self._gitlab_url)

        console.print("[dim]Fetching pipeline data from GitLab…[/]")
        data = await anyio.to_thread.run_sync(
            lambda: backend.get_failed_pipeline_data(project, pipeline_id)
        )

        prompt = _build_direct_prompt(data)
        console.print("[dim]Sending to Gemini for analysis…[/]")

        response = self._genai.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.1,
            ),
        )
        final_text = response.text or ""
        report = _parse_report(final_text, project, data["pipeline_id"])
        report.pipeline_url = data.get("pipeline_url", "")

        if post_comment and report.full_analysis:
            sha = data.get("sha", "")
            url = await anyio.to_thread.run_sync(
                lambda: backend.post_pipeline_comment(project, sha, _format_comment(report))
            )
            report.mr_comment_url = url or None

        return report


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _fmt_args(args: dict[str, Any]) -> str:
    s = json.dumps(args, default=str)
    return (s[:70] + "…") if len(s) > 70 else s


def _build_direct_prompt(data: dict[str, Any]) -> str:
    lines = [
        f"Project: {data['project']}",
        f"Pipeline: #{data['pipeline_id']} ({data['pipeline_status']}) ref={data.get('ref', '?')}",
        f"URL: {data.get('pipeline_url', 'N/A')}",
        "",
        "Failed jobs:",
    ]
    for job in data.get("failed_jobs", []):
        lines += [
            f"\n--- Job: {job['name']} (stage: {job['stage']}, status: {job['status']}) ---",
            f"failure_reason: {job.get('failure_reason') or 'N/A'}",
            "Log tail:",
            job["log_tail"],
        ]
    return "\n".join(lines)


def _sanitize_json(s: str) -> str:
    """Escape literal control characters inside JSON string values.

    Gemini sometimes writes literal newlines/tabs inside string values
    (e.g. in diff fields), producing invalid JSON.  Walk the token stream
    and replace bare control chars with their JSON escape sequences.
    """
    out: list[str] = []
    in_str = False
    escaped = False
    _escapes = {"\n": "\\n", "\r": "\\r", "\t": "\\t"}
    for ch in s:
        if escaped:
            out.append(ch)
            escaped = False
        elif ch == "\\":
            out.append(ch)
            escaped = True
        elif ch == '"':
            out.append(ch)
            in_str = not in_str
        elif in_str and ch in _escapes:
            out.append(_escapes[ch])
        else:
            out.append(ch)
    return "".join(out)


def _extract_json_block(text: str) -> str | None:
    """Extract the first JSON object from a ```json ... ``` block.

    Uses brace-counting rather than regex so embedded triple-backticks
    inside string values (e.g. diffs) don't terminate the match early.
    """
    start = text.find("```json")
    if start == -1:
        return None
    brace_start = text.find("{", start)
    if brace_start == -1:
        return None
    depth = 0
    in_str = False
    escaped = False
    for i, ch in enumerate(text[brace_start:], brace_start):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and in_str:
            escaped = True
            continue
        if ch == '"':
            in_str = not in_str
            continue
        if not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[brace_start : i + 1]
    return None


def _parse_report(text: str, project: str, pipeline_id: int | None) -> DiagnosisReport:
    """Extract a DiagnosisReport from the agent's final text response."""
    raw_json = _extract_json_block(text)
    if raw_json is not None:
        try:
            data = json.loads(_sanitize_json(raw_json))
            proposals = [
                FixProposal(
                    file_path=p.get("file_path", ""),
                    description=p.get("description", ""),
                    diff=p.get("diff", ""),
                    confidence=Confidence(p.get("confidence", "medium")),
                )
                for p in data.get("fix_proposals", [])
            ]
            return DiagnosisReport(
                project=project,
                pipeline_id=pipeline_id,
                root_cause=data.get("root_cause", "see full analysis"),
                failure_category=FailureCategory(
                    data.get("failure_category", "unknown")
                ),
                affected_jobs=data.get("affected_jobs", []),
                is_flaky=bool(data.get("is_flaky", False)),
                fix_proposals=proposals,
                full_analysis=text,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.debug("Could not parse structured report: %s", exc)

    return DiagnosisReport(
        project=project,
        pipeline_id=pipeline_id,
        root_cause="See full analysis below",
        full_analysis=text,
    )


def _format_comment(report: DiagnosisReport) -> str:
    lines = [
        "## PipelineGuard Diagnosis",
        "",
        f"**Root cause:** {report.root_cause}",
        f"**Category:** `{report.failure_category.value}`",
        f"**Affected jobs:** {', '.join(f'`{j}`' for j in report.affected_jobs) or '(see below)'}",
    ]
    if report.is_flaky:
        lines.append("\n> This failure appears **flaky** — consider retrying before applying a fix.")
    if report.fix_proposals:
        lines.append("\n### Proposed fixes")
        for i, fix in enumerate(report.fix_proposals, 1):
            lines += [
                f"\n**{i}. `{fix.file_path}`** ({fix.confidence.value} confidence)",
                fix.description,
            ]
            if fix.diff:
                lines += ["\n```diff", fix.diff, "```"]
    lines += [
        "",
        "---",
        "*Generated by [PipelineGuard](https://github.com/64johnlee/hackathon-pipeline-guard)*"
        " — powered by Gemini 2.5 Flash · official GitLab MCP + PipelineGuard MCP",
    ]
    return "\n".join(lines)
