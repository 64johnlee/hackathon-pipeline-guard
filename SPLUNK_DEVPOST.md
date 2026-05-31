# SplunkGuard — Devpost Submission Copy

> Submission text for the [Splunk Agentic Ops Hackathon](https://splunk.devpost.com/) — Observability track + Best Use of Splunk MCP Server.
> Each section maps to a standard Devpost field. SplunkGuard has no live URL (it queries a local Splunk instance) — the demo video carries the demo. Verify the benchmark numbers reflect your final recorded run before submitting.

## Tagline
Ask your Splunk a question in plain English — "what failed last night and why?" — and get back a structured root cause with paste-ready SPL. No query language required.

## Inspiration
Splunk is where the answers live, but getting them means knowing SPL, knowing your indexes, and knowing which fields matter. That's a steep wall between a stressed on-call engineer and the data that would resolve their incident. We wanted to put a fluent Splunk analyst behind a single natural-language prompt — one that writes the SPL, picks the time window, and explains *why*, not just *what*.

## What it does
SplunkGuard is a Gemini-driven agent that investigates operational questions against your Splunk data. You ask something like *"What CI pipelines failed and what's the failure category?"* or *"Are there auth anomalies in the last 24h?"*, and the agent:

1. **Decides the search** — index, time window, and SPL — so you write none of it.
2. **Queries Splunk** through one of two backends (REST or the official MCP Server).
3. **Returns a structured `SplunkInvestigationReport`**: `root_cause`, `investigation_category`, `affected_components`, `time_range`, `is_ongoing`, and a list of `recommended_actions` — each with a **paste-ready SPL query and a confidence level**.

It ships with a GitLab→Splunk **HEC ingester** so you can populate a fresh Splunk with real CI/CD telemetry (`gitlab:pipeline` / `gitlab:job` events) and have something meaningful to investigate in minutes.

## How we built it
SplunkGuard runs **Gemini 2.5 Flash** (Google AI Studio or Vertex AI) over two interchangeable Splunk backends:

- **`--direct` (REST):** posts an SPL search job to `/services/search/jobs`, polls to completion, and returns a structured report in **one Gemini call** — **8.48 seconds** end-to-end.
- **MCP (default):** talks to **Splunkbase App #7931 (Splunk MCP Server)** over the modern **Streamable HTTP transport** (MCP 2025-06-18 spec) at `/services/mcp`. Tool discovery is **fully dynamic** — the agent reads the server's advertised tools via `list_tools()`, translates them into Gemini `FunctionDeclaration`s, and iterates. **No Splunk MCP tool name is ever hardcoded.**

Both paths emit the same Pydantic-validated report schema, so you can swap backends without changing anything downstream.

## Accomplishments we're proud of
We verified **both paths end-to-end against real Splunk Enterprise** instances, with **294 events** (30 pipelines + 264 jobs) ingested from the public `gitlab-org/cli` project:

| Mode | Splunk | Time | Result |
|---|---|---|---|
| `--direct` (REST) | 10.4.0 | **8.48 s** | 1 Gemini call, structured report |
| **MCP** (App #7931 v1.1.0) | 10.4.0 *or* 9.4.11 | **37.84 s** | Gemini autonomously calls 2 MCP tools; *deeper* analysis — names the specific failing job (`code_navigation_golang`), infers `is_ongoing`, returns 3 SPL recommendations |

Cold start to first answer — blank Splunk → ingest → investigate — is **~45 seconds**.

## Challenges we ran into
- **A restart foot-gun that cost us a day.** Splunkbase App #7931 wouldn't activate, and we initially blamed Splunk 10.4. The real cause: inside the Docker image, `splunk restart` kills splunkd but never re-spawns it. Switching to **`docker restart`** fixed it instantly — and the app then booted cleanly on **both 10.4.0 and 9.4.11**. We documented this precisely so nobody else loses that day.
- **Structured output discipline.** Forcing the model to consistently return a valid `SplunkInvestigationReport` (with embedded SPL that itself contains quotes and pipes) took careful schema and sanitization work.
- **Self-signed TLS** on local Splunk dev instances — we made `--no-verify-ssl` flow correctly through the MCP backend.

## What we learned
The MCP path is ~4× slower than direct REST, but that latency *buys* something: given real tool-call budget, Gemini iterates and produces more specific findings (exact job names, ongoing-incident inference). The right answer isn't "always MCP" or "always REST" — it's exposing both and letting the use case pick: sub-10-second loops via `--direct`, richer investigations via MCP.

## What's next
Scheduled/standing investigations that alert on regressions, multi-index correlation, a richer recommended-action library, and feeding SplunkGuard's findings back into PipelineGuard's CI auto-fix loop for a closed observability-to-remediation cycle.

## Built with
`Gemini 2.5 Flash` · `Splunk MCP Server (App #7931)` · `Model Context Protocol (Streamable HTTP)` · `Splunk Enterprise 10.4 / 9.4` · `Splunk HEC` · `Splunk REST API` · `python` · `Pydantic v2` · `google-genai SDK` · `Vertex AI`

## Links
- **GitHub:** https://github.com/64johnlee/hackathon-pipeline-guard
- **Full SplunkGuard docs:** [SPLUNK.md](https://github.com/64johnlee/hackathon-pipeline-guard/blob/main/SPLUNK.md)

## Prizes targeted
Observability track ($3,000, primary) + Best Use of Splunk MCP Server ($1,000) — both **verified** end-to-end.

## Submission note
SplunkGuard has no public live URL (it queries a local/private Splunk instance), so the demo carries the walkthrough — embed `demo/splunkguard_demo.mp4` (720p, ~2m14s) in the Devpost submission.
