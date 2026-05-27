# SplunkGuard

> AI-powered Splunk observability investigations: ask a natural-language question, Gemini 2.5 Flash queries your Splunk and returns a structured root cause with SPL-backed recommended actions.

**Submitted to:** [Splunk Agentic Ops Hackathon](https://splunk.devpost.com/) — **Observability** track + **Best Use of Splunk MCP Server**.

SplunkGuard is a Gemini-driven agent that investigates operational questions against your Splunk data. Ask *"What CI pipelines failed last night and why?"* or *"Are there auth anomalies in the last 24h?"* — Gemini queries Splunk (via the official MCP Server or REST), synthesizes a structured `SplunkInvestigationReport` (root cause, category, time range, affected components, recommended actions with paste-ready SPL).

**Both paths verified end-to-end** against a real Splunk Enterprise instance with **~294 events** (30 pipelines + ~264 jobs) ingested from the public `gitlab-org/cli` project:

| Mode | Splunk | Time | Notes |
|---|---|---|---|
| `--direct` (REST) | 10.4.0 | **8.48 s** | 1 Gemini call · same structured output |
| **MCP** (App #7931) | 10.4.0 *or* 9.4.11 | **37.84 s** | Gemini autonomously calls 2 MCP tools · deeper analysis (identifies specific failing job names like `code_navigation_golang`, infers `is_ongoing: true`). Verified on both Splunk versions when installed with `docker restart` (not `splunk restart`) |

See [Benchmark](#benchmark) for full numbers.

---

## Architecture

```
User question (natural language)
      │
      ▼
┌──────────────────────────────────────────────────┐
│  SplunkGuardAgent  (pipelineguard/splunk_agent)  │
│                                                  │
│  ┌──────────────────┐   ┌──────────────────────┐ │
│  │ Gemini 2.5 Flash │◄──┤ Single-call (direct) │ │
│  │ (google-genai)   │   │  or tool loop (MCP)  │ │
│  └──────────────────┘   └──────────┬───────────┘ │
└────────────────────────────────────┼─────────────┘
                                     │
                ┌────────────────────┴─────────────────────┐
                │                                          │
                │ Primary: --direct (REST)                 │ Future: MCP (HTTP/SSE)
                ▼                                          ▼
   ┌─────────────────────────────┐         ┌──────────────────────────────────┐
   │ SplunkDirectBackend         │         │ SplunkMCPBackend                 │
   │ (pipelineguard/backends/    │         │ (pipelineguard/backends/         │
   │  splunk_direct.py)          │         │  splunk_mcp.py)                  │
   │                             │         │                                  │
   │ - POST /services/search/jobs│         │ Targets Splunkbase App #7931     │
   │ - poll until done           │         │ (Splunk MCP Server, beta).       │
   │ - GET results               │         │ Currently blocked: v1.1.0 of the │
   │ - Bearer token auth         │         │ app + Splunk Enterprise 10.4.0   │
   └──────────────┬──────────────┘         │ won't restart cleanly together   │
                  │                        │ (audited; not our code). REST    │
                  │ HTTPS                  │ fallback used for submission.    │
                  ▼                        └──────────────────────────────────┘
   ┌─────────────────────────────┐
   │ Splunk Enterprise / Cloud   │
   │ - Indexed CI/CD logs        │
   │ - Saved searches            │
   │ - Metrics & events          │
   └─────────────────────────────┘

Ingestion path (CI/CD → Splunk):  pipelineguard/ingesters/gitlab_to_splunk.py
  GitLab API → batched HEC events (sourcetype=gitlab:pipeline / gitlab:job)
  → Splunk index "pipelineguard" → queryable by SplunkGuardAgent.
  Benchmark: 30 pipelines + 264 jobs = 294 HEC events in 37s.
```

**On the MCP integration.** SplunkGuard's MCP code path is implemented, audited, and end-to-end verified on **Splunk Enterprise 9.4.11 + Splunkbase App #7931 v1.1.0**. The backend uses the modern **MCP Streamable HTTP transport** (per the MCP 2025-06-18 spec) — not the older SSE transport — talking to `/services/mcp` on the Splunk management port (8089) with `Authorization: Splunk <encrypted-token>`. Tool discovery is fully dynamic (`list_tools()` → Gemini `FunctionDeclaration`s); the agent never hardcodes a Splunk MCP tool name. Two gotchas worth knowing if you reproduce:

1. **`docker restart` after install, not `splunk restart`.** This is the *only* gotcha — and it's an issue with the Splunk Docker image's entrypoint script, not with App #7931 itself. The in-container `splunk restart` command receives an interrupt signal but never re-spawns the daemon (splunkd stays dead). Use `docker restart splunk` instead and Docker's entrypoint correctly re-boots splunkd with the newly-installed app.
2. **Splunk 10.4 *and* 9.4 both work.** We initially reported 10.4 as broken — that was a misdiagnosis. The real root cause was `splunk restart` (point 1 above). After switching to `docker restart`, App #7931 v1.1.0 installs and boots cleanly on `splunk/splunk:latest` (verified on 10.4.0) as well as `splunk/splunk:9.4` (verified on 9.4.11). Either image is fine — `:latest` is the easiest reproduce.

---

## Quick Start

### 1. Install Splunk Enterprise (free trial)

```bash
# Linux/macOS — fastest path is the Splunk Free single-instance Docker image.
# Note: the SPLUNK_GENERAL_TERMS flag was added by Splunk in late 2025 — both
# license flags are required.
docker run -d --name splunk \
  -p 8000:8000 -p 8088:8088 -p 8089:8089 \
  -e SPLUNK_PASSWORD=changeme \
  -e SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com \
  -e SPLUNK_START_ARGS=--accept-license \
  splunk/splunk:latest

# Wait ~60s for boot, then open http://localhost:8000  (admin / changeme)
```

### 2. Create a Splunk auth token + HEC token

The `--direct` mode uses a standard Splunk auth Bearer token; the ingester
uses an HEC token to POST events. Both can be created via REST:

```bash
# Bearer token for --direct mode (valid 30 days, scoped to splunkguard):
curl -sk -u "admin:changeme" -X POST \
  "https://localhost:8089/services/authorization/tokens?output_mode=json" \
  -d "name=admin&audience=splunkguard&not_before=%2B0d&expires_on=%2B30d" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entry'][0]['content']['token'])"

# HEC token for the ingester (writes into the 'pipelineguard' index):
curl -sk -u "admin:changeme" -X POST \
  "https://localhost:8089/servicesNS/nobody/splunk_httpinput/data/inputs/http?output_mode=json" \
  -d "name=hackathon&index=pipelineguard&sourcetype=manual&disabled=0&useACK=0" \
  | python3 -c "import json,sys; print(json.load(sys.stdin)['entry'][0]['content']['token'])"

# Create the index:
curl -sk -u "admin:changeme" -X POST \
  "https://localhost:8089/services/data/indexes?output_mode=json" \
  -d "name=pipelineguard&datatype=event"
```

> **For the MCP path** (default when `--direct` is not passed):
>
> ```bash
> # Splunk Enterprise (either splunk/splunk:latest or splunk/splunk:9.4 work)
> docker run -d --name splunk \
>   -p 8000:8000 -p 8088:8088 -p 8089:8089 \
>   -e SPLUNK_PASSWORD=changeme \
>   -e SPLUNK_GENERAL_TERMS=--accept-sgt-current-at-splunk-com \
>   -e SPLUNK_START_ARGS=--accept-license \
>   splunk/splunk:latest
>
> # Once healthy (~60s), install Splunkbase App #7931 (the .tgz can be
> # downloaded after logging into splunkbase.splunk.com):
> docker cp splunk_mcp_server.tgz splunk:/tmp/
> docker exec -u splunk splunk /opt/splunk/bin/splunk install app \
>   /tmp/splunk_mcp_server.tgz -auth admin:changeme
> # IMPORTANT: restart the *container*, not splunkd. `splunk restart` kills
> # splunkd but never re-spawns it in Docker; `docker restart` does.
> docker restart splunk
>
> # Generate the MCP token:
> curl -sk -u admin:changeme -X POST \
>   "https://localhost:8089/services/mcp_token?username=admin&action=rotate"
> curl -sk -u admin:changeme \
>   "https://localhost:8089/services/mcp_token?username=admin&action=get"
> # → use the returned encrypted token as SPLUNK_MCP_TOKEN in .env
> ```

### 3. Install PipelineGuard

```bash
git clone https://github.com/64johnlee/hackathon-pipeline-guard
cd hackathon-pipeline-guard
pip install -e .
```

### 4. Configure

```bash
cp .env.example .env
# Edit .env:
#   GEMINI_API_KEY=...                       # AI Studio key (free tier OK)
#   SPLUNK_TOKEN=<the Bearer token>          # from step 2 (Bearer)
#   SPLUNK_HEC_TOKEN=<the HEC token>         # from step 2 (HEC)
#   SPLUNK_HOST=localhost
#   SPLUNK_PORT=8089
#   SPLUNK_HEC_URL=https://localhost:8088
#   SPLUNK_VERIFY_SSL=false                  # local dev self-signed cert
```

### 5. (Optional) Ingest sample CI/CD logs

If you don't have CI/CD data in Splunk yet, pump some GitLab data in:

```bash
# Requires GITLAB_TOKEN (api + read_repository scopes) and SPLUNK_HEC_TOKEN
pipelineguard splunk ingest --project myorg/myrepo --since -7d
```

This populates Splunk's `pipelineguard` index with `gitlab:pipeline` and
`gitlab:job` events (with log tails on failed/canceled jobs) so SplunkGuard
has real data to investigate.

### 6. Investigate

```bash
# Natural-language question, default --direct path:
pipelineguard splunk investigate \
  "What CI pipelines failed in this Splunk instance and what's the failure category?" \
  --earliest -30d --latest now \
  --direct --no-verify-ssl \
  --splunk-token "$SPLUNK_TOKEN"
```

The agent picks the time window, the index, the SPL syntax — you don't write
any SPL yourself. Output is a structured `SplunkInvestigationReport`:

```
╭─────────────────────────────────────────────────────────────────────╮
│ SplunkGuard · What CI pipelines failed in this Splunk instance ...  │
│ time range: -30d → now · mode: direct                               │
╰─────────────────────────────────────────────────────────────────────╯
Fetching context from Splunk REST API…
Sending to Gemini for analysis…

I executed a query against the pipelineguard index, specifically looking for
events where the status field indicates a failure (e.g., "failed", "canceled")
and a failure_reason is present. The query covered the specified time range of
-30d to now.

The search revealed several failed CI pipeline jobs. For instance, on
2026-05-27 at 07:03:44 UTC, a job with pipeline_id 2555261703 and job_id
14557438274 from the gitlab-org/cli project, named "tests:unit", was found with
a "canceled" status. Another job, "tests:integration", from the same pipeline
and project, also showed a "canceled" status around the same time. The
failure_reason for these specific events was "canceled by user".

{
  "root_cause": "Multiple CI pipeline jobs in the 'gitlab-org/cli' project were
canceled by a user, specifically the 'tests:unit' and 'tests:integration' jobs.",
  "investigation_category": "pipeline_failure",
  "affected_components": ["gitlab-org/cli CI/CD pipeline"],
  "time_range": "2026-04-27 07:03 – 2026-05-27 07:03 UTC",
  "is_ongoing": false,
  "recommended_actions": [
    {
      "action": "Review the specific pipeline runs and associated logs for the
'gitlab-org/cli' project to understand the context and impact of the
user-initiated cancellations.",
      "spl_query": "index=pipelineguard project=\"gitlab-org/cli\"
status=\"canceled\" | table _time, pipeline_id, job_id, project, name, status,
failure_reason, web_url",
      "confidence": "high"
    },
    {
      "action": "Monitor for any new pipeline failures or cancellations in the
'pipelineguard' index, especially those with non-user-initiated failure reasons.",
      "spl_query": "index=pipelineguard status!=success failure_reason!=null |
stats count by project, name, status, failure_reason | sort -count",
      "confidence": "high"
    }
  ]
}
```

> Output above is **verbatim** from a real run on 2026-05-27. Total wall-clock
> time from CLI invocation to structured report: **8.48 seconds**.

---

## Benchmark

| Stage | Wall-clock | Notes |
|---|---|---|
| **Ingest** (`pipelineguard splunk ingest gitlab-org/cli --since -7d --max-pipelines 30`) | **37 s** | 30 pipelines + 264 jobs = 294 HEC events posted to Splunk |
| **Investigate — `--direct`** (REST, 1 Gemini call) | **8.48 s** | Splunk 10.4.0; pre-fetches index list + 200-event sample, one Gemini call returns structured report |
| **Investigate — MCP** (App #7931, agentic loop) | **37.84 s** | Splunk 10.4.0 or 9.4.11 + Splunkbase App #7931 v1.1.0; Gemini autonomously calls 2 MCP tools and produces a more nuanced report (identifies specific job names like `code_navigation_golang`, infers `is_ongoing: true`, returns 3 SPL recommendations vs. 2 in direct mode). Use `docker restart` after installing the app — `splunk restart` is the foot-gun |
| **End-to-end** (cold Splunk + ingest + investigate, `--direct` path) | **~45 s** | From "blank Splunk" to "first answer" |

**Environment:**
- Splunk Enterprise 10.4.0 *or* 9.4.11 (Docker, `splunk/splunk:latest` or `splunk/splunk:9.4`)
- Splunkbase App #7931 v1.1.0 (for the MCP path; installed via the bundled `.tgz` then `docker restart splunk`)
- Gemini 2.5 Flash via Google AI Studio (free tier), Python 3.13.

The MCP path is roughly 4× slower than `--direct` because it gives Gemini real tool-call latency budget to iterate; the trade-off is deeper, more specific findings. Pick `--direct` for sub-10-second loops and `--mcp` (default when `--direct` not passed) for richer single-shot investigations.

---

## CLI reference

| Command | What it does |
|---|---|
| `pipelineguard splunk investigate "<question>"` | Run an investigation. Default mode: MCP. Add `--direct` to skip MCP. |
| `pipelineguard splunk investigate ... --earliest -6h --latest now` | Restrict the time window. |
| `pipelineguard splunk ingest --project myorg/myrepo` | Pump GitLab pipelines + jobs into Splunk via HEC. |
| `pipelineguard splunk ingest --project ... --since -7d` | Backfill 7 days of pipeline history. |

---

## Configuration

| Env var | What | Required |
|---|---|---|
| `GEMINI_API_KEY` | Google AI Studio key (free tier OK) | Yes (or use `--vertex` for Vertex AI) |
| `SPLUNK_MCP_TOKEN` | Encrypted token from Splunk MCP Server App UI | Yes (for MCP mode) |
| `SPLUNK_MCP_URL` | Splunk MCP endpoint (default `https://localhost:8089/services/mcp`) | No (defaults shown) |
| `SPLUNK_HEC_TOKEN` | HTTP Event Collector token (for `ingest` command only) | Only for ingest |
| `SPLUNK_HEC_URL` | HEC endpoint (default `https://localhost:8088`) | No |

For self-signed certs in local Splunk dev instances, pass `--no-verify-ssl` to skip TLS verification (the MCP backend now honors this — fixed in commit after audit).

---

## Prize targeting

| Prize | Status |
|---|---|
| **Observability** track ($3,000) | **Primary target — verified.** SplunkGuard's headline use case is CI/CD failure triage — classic observability. Real-world demo: GitLab pipeline logs ingested via HEC → indexed in Splunk → investigated via natural language. End-to-end verified on Splunk Enterprise 10.4 + REST and on Splunk Enterprise 9.4 + MCP (see [Benchmark](#benchmark)). |
| **Best Use of Splunk MCP Server** ($1,000) | **Secondary target — verified.** SplunkGuard talks to Splunkbase App #7931 over the official Streamable HTTP MCP transport. Tool discovery is fully dynamic (no hardcoded tool names); the agent translates the server's advertised tools into Gemini `FunctionDeclaration`s and iterates. Verified end-to-end on Splunk 9.4.11 + App #7931 v1.1.0: 37.84 s investigation, 2 MCP tool calls, structured report with paste-ready SPL. |

Combined target: **$4,000**. Grand Prize ($7,000) and other "Best Use" prizes (Hosted Models, Developer Tools) are theoretically in play but not the primary target.

---

## License

MIT — same as the rest of the project.
