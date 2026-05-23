# PipelineGuard / SplunkGuard — Architecture Diagram

## System Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        User / CI Webhook                        │
│   pipelineguard diagnose myorg/myrepo                           │
│   pipelineguard splunk investigate "why did builds fail at 2am" │
└───────────────────────────┬─────────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Agent Orchestration Layer                   │
│              pipelineguard/agent.py  |  splunk_agent.py         │
│                                                                 │
│   ┌──────────────────┐      ┌──────────────────────────────┐    │
│   │  Gemini 2.0 Flash│◄────►│    Agentic Tool-Call Loop    │    │
│   │  (google-genai)  │      │    (up to 15 iterations)     │    │
│   └──────────────────┘      └──────────────┬───────────────┘    │
└────────────────────────────────────────────┼────────────────────┘
                                             │  MCP function calls
                    ┌────────────────────────┴──────────────────┐
                    │            Backend Interface               │
                    │  list_tools_as_gemini() / call_tool()     │
                    └──────┬──────────────────────┬─────────────┘
                           │                      │
              ┌────────────▼────────┐  ┌──────────▼───────────┐
              │  GitLab MCP Backend │  │  Splunk MCP Backend   │
              │  (stdio / npx)      │  │  (HTTP/SSE port 8089) │
              │                     │  │                        │
              │  @gitlab-org/       │  │  Splunk MCP Server App │
              │  mcp-gitlab         │  │  (Splunkbase ID 7931)  │
              └────────────┬────────┘  └──────────┬────────────┘
                           │                      │
              ┌────────────▼────────┐  ┌──────────▼────────────┐
              │    GitLab API       │  │     Splunk REST API    │
              │    (HTTPS)          │  │     (SPL queries)      │
              └─────────────────────┘  └───────────────────────┘
```

## Data Flow

### GitLab Mode (PipelineGuard)

```
1. User runs: pipelineguard diagnose myorg/myrepo
2. Agent sends initial prompt to Gemini 2.0 Flash
3. Gemini calls: list_pipelines → finds latest failed pipeline
4. Gemini calls: get_pipeline_jobs → lists failed jobs
5. Gemini calls: get_job_log (per failed job) → fetches raw logs
6. Gemini iterates: cross-references logs, identifies root cause
7. Gemini calls: create_note (optional) → posts MR comment
8. Agent returns: DiagnosisReport with root_cause + fix_proposals
```

### Splunk Mode (SplunkGuard)

```
1. User runs: pipelineguard splunk investigate "query"
2. Agent sends investigation prompt to Gemini 2.0 Flash
3. Gemini calls: get_indexes → discovers available data sources
4. Gemini calls: generate_spl → converts question to SPL query
5. Gemini calls: run_splunk_query → executes SPL, gets events
6. Gemini iterates: refines queries, correlates across indexes
7. Agent returns: SplunkInvestigationReport with root_cause + recommended_actions
```

## AI Model Integration

| Component | Technology | Role |
|---|---|---|
| LLM | Gemini 2.0 Flash (`gemini-2.0-flash`) | Reasoning, tool orchestration, report generation |
| Protocol | Model Context Protocol (MCP) open standard | AI-to-service communication |
| GitLab tools | `@gitlab-org/mcp-gitlab` (official) | Pipeline/job/log access |
| Splunk tools | Splunk MCP Server App v1.0+ | SPL execution, index discovery, AI-assisted queries |

## Fallback Mode

When the MCP server is unavailable, both agents fall back to direct REST API calls:

```
GitLab fallback:  python-gitlab → GitLab REST API
Splunk fallback:  httpx → Splunk REST API (/services/search/jobs)
```

## Component Dependencies

```
pipelineguard/
├── agent.py              ← PipelineGuardAgent (GitLab)
├── splunk_agent.py       ← SplunkGuardAgent (Splunk)
├── models.py             ← DiagnosisReport dataclass
├── prompts.py            ← GitLab system prompt
├── splunk_prompts.py     ← Splunk system prompt
├── cli.py                ← Click CLI entry point
└── backends/
    ├── mcp.py            ← GitLab stdio MCP client
    ├── direct.py         ← GitLab python-gitlab fallback
    ├── splunk_mcp.py     ← Splunk HTTP/SSE MCP client
    └── splunk_direct.py  ← Splunk REST API fallback
```

## Key Design Decisions

1. **Backend interface contract** — both MCP backends expose identical `list_tools_as_gemini()` and `call_tool()` methods, making the agent loop completely platform-agnostic.

2. **Graceful degradation** — if the MCP server is missing, both agents fall back to direct API calls, ensuring the tool works in any environment.

3. **Structured output** — all reports end with a JSON block (`root_cause`, `fix_proposals`, confidence scores), enabling downstream automation without LLM re-invocation.

4. **Iteration cap** — the tool-call loop is capped at 15 iterations to bound cost and latency while still allowing multi-step investigation.
