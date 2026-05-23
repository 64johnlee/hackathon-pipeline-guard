"""SplunkGuard agent — orchestrates Gemini + Splunk MCP/direct backends."""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from google import genai
from google.genai import types
from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn

from .backends.splunk_direct import SplunkDirectBackend
from .backends.splunk_mcp import SplunkMCPBackend
from .splunk_prompts import SPLUNK_SYSTEM_PROMPT, build_splunk_prompt

logger = logging.getLogger(__name__)
console = Console()

_GEMINI_MODEL = "gemini-2.0-flash"
_MAX_TOOL_ITERATIONS = 15


# ---------------------------------------------------------------------------
# Result model
# ---------------------------------------------------------------------------

@dataclass
class SplunkInvestigationReport:
    question: str
    root_cause: str
    investigation_category: str = "unknown"
    affected_components: list[str] = field(default_factory=list)
    time_range: str = ""
    is_ongoing: bool = False
    recommended_actions: list[dict[str, str]] = field(default_factory=list)
    full_analysis: str = ""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class SplunkGuardAgent:
    """
    Investigates Splunk data using a Gemini agentic loop over the Splunk MCP Server.

    Primary mode:  Gemini tool-call loop via Splunk MCP Server (HTTP/SSE).
    Fallback mode: direct SPL query via Splunk REST API + single Gemini call.
    """

    def __init__(
        self,
        gemini_api_key: str,
        splunk_token: str,
        splunk_url: str = "https://localhost:8089/services/mcp",
        splunk_host: str = "localhost",
        splunk_port: int = 8089,
        verify_ssl: bool = True,
        force_direct: bool = False,
    ) -> None:
        self._genai = genai.Client(api_key=gemini_api_key)
        self._splunk_token = splunk_token
        self._splunk_url = splunk_url
        self._splunk_host = splunk_host
        self._splunk_port = splunk_port
        self._verify_ssl = verify_ssl
        self._use_mcp = (not force_direct) and SplunkMCPBackend.is_available()

    async def investigate(
        self,
        question: str,
        earliest: str = "-24h",
        latest: str = "now",
    ) -> SplunkInvestigationReport:
        mode = "MCP" if self._use_mcp else "direct"
        console.print(
            Panel(
                f"[bold cyan]SplunkGuard[/] · [green]{question[:80]}{'…' if len(question) > 80 else ''}[/]\n"
                f"[dim]time range: {earliest} → {latest} · mode: {mode}[/]",
                border_style="cyan",
            )
        )
        if self._use_mcp:
            return await self._investigate_mcp(question, earliest, latest)
        return await self._investigate_direct(question, earliest, latest)

    # ------------------------------------------------------------------
    # MCP mode — reuses the same agentic tool loop pattern as PipelineGuard
    # ------------------------------------------------------------------

    async def _investigate_mcp(
        self,
        question: str,
        earliest: str,
        latest: str,
    ) -> SplunkInvestigationReport:
        async with SplunkMCPBackend(
            splunk_token=self._splunk_token,
            splunk_url=self._splunk_url,
            verify_ssl=self._verify_ssl,
        ) as backend:
            tools = await backend.list_tools_as_gemini()
            prompt = build_splunk_prompt(question, earliest, latest)
            messages: list[types.Content] = [
                types.Content(role="user", parts=[types.Part(text=prompt)])
            ]
            final_text = await self._run_tool_loop(backend, tools, messages)
        return _parse_report(final_text, question)

    async def _run_tool_loop(
        self,
        backend: SplunkMCPBackend,
        tools: list[types.Tool],
        messages: list[types.Content],
    ) -> str:
        """Identical loop structure to PipelineGuardAgent._run_tool_loop."""
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
                        system_instruction=SPLUNK_SYSTEM_PROMPT,
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
                    result_text = await backend.call_tool(fc.name, dict(fc.args))
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
    # Direct mode — pre-run searches, single Gemini call
    # ------------------------------------------------------------------

    async def _investigate_direct(
        self,
        question: str,
        earliest: str,
        latest: str,
    ) -> SplunkInvestigationReport:
        backend = SplunkDirectBackend(
            host=self._splunk_host,
            port=self._splunk_port,
            token=self._splunk_token,
            verify_ssl=self._verify_ssl,
        )
        console.print("[dim]Fetching context from Splunk REST API…[/]")
        try:
            info = backend.get_server_info()
            indexes = backend.list_indexes()
            # Broad sample to give Gemini raw events to reason over
            sample = backend.run_search(
                f"index=* earliest={earliest} latest={latest} | head 200",
                earliest=earliest,
                latest=latest,
                max_results=200,
            )
        except Exception as exc:
            logger.warning("Splunk direct fetch failed: %s", exc)
            info, indexes, sample = {}, [], []

        context = (
            f"Splunk instance: {info}\n"
            f"Available indexes: {indexes}\n"
            f"Sample events (up to 200):\n{json.dumps(sample, default=str)[:8000]}"
        )
        prompt = build_splunk_prompt(question, earliest, latest) + f"\n\nContext:\n{context}"

        console.print("[dim]Sending to Gemini for analysis…[/]")
        response = self._genai.models.generate_content(
            model=_GEMINI_MODEL,
            contents=[types.Content(role="user", parts=[types.Part(text=prompt)])],
            config=types.GenerateContentConfig(
                system_instruction=SPLUNK_SYSTEM_PROMPT,
                temperature=0.1,
            ),
        )
        return _parse_report(response.text or "", question)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fmt_args(args: dict[str, Any]) -> str:
    s = json.dumps(args, default=str)
    return (s[:70] + "…") if len(s) > 70 else s


def _parse_report(text: str, question: str) -> SplunkInvestigationReport:
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            return SplunkInvestigationReport(
                question=question,
                root_cause=data.get("root_cause", "see full analysis"),
                investigation_category=data.get("investigation_category", "unknown"),
                affected_components=data.get("affected_components", []),
                time_range=data.get("time_range", ""),
                is_ongoing=bool(data.get("is_ongoing", False)),
                recommended_actions=data.get("recommended_actions", []),
                full_analysis=text,
            )
        except (json.JSONDecodeError, ValueError, KeyError) as exc:
            logger.debug("Could not parse structured report: %s", exc)

    return SplunkInvestigationReport(
        question=question,
        root_cause="See full analysis below",
        full_analysis=text,
    )
