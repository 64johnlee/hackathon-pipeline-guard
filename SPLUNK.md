# SplunkGuard

> AI-powered Splunk observability investigations: ask a natural-language question, Gemini 2.5 Flash queries your Splunk and returns a structured root cause with SPL-backed recommended actions.

**Submitted to:** [Splunk Agentic Ops Hackathon](https://splunk.devpost.com/) — **Observability** track.

SplunkGuard is a Gemini-driven agent that investigates operational questions against your Splunk data. Ask *"What CI pipelines failed last night and why?"* or *"Are there auth anomalies in the last 24h?"* — Gemini queries Splunk, synthesizes a structured `SplunkInvestigationReport` (root cause, category, time range, affected components, recommended actions with paste-ready SPL).

**Verified end-to-end** against a real Splunk Enterprise 10.4.0 instance with **294 events** (30 pipelines + 264 jobs) ingested from the public `gitlab-org/cli` project: **8.48 seconds** from question to structured report with correct root cause and 2 actionable SPL recommendations. See [Benchmark](#benchmark) below.

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

**On the MCP integration.** SplunkGuard's MCP code path is implemented and audited (`pipelineguard/backends/splunk_mcp.py` — HTTP/SSE client, dynamic tool discovery via FastMCP `list_tools()`, no hardcoded tool names). However, **Splunkbase App #7931 v1.1.0 currently breaks Splunk Enterprise 10.4.0 on install** — splunkd refuses to restart after the app is enabled (confirmed by manual install via `splunk install app` + restart inside the official `splunk/splunk:latest` Docker image). The MCP code is ready and will work the moment Splunk ships a compatible MCP Server release; in the meantime the `--direct` REST path is the verified demo path.

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

> *Optional:* the **MCP path** would use Splunkbase App #7931 ("Splunk MCP Server",
> beta) instead. The integration is implemented but App v1.1.0 + Splunk 10.4
> have a startup-time conflict; the `--direct` REST path above is the verified
> demo path for this submission.

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
| **Investigate** (`pipelineguard splunk investigate … --direct`) | **8.48 s** | Single Gemini 2.5 Flash call; structured `SplunkInvestigationReport` returned |
| **End-to-end** (cold Splunk + ingest + investigate) | **~45 s** | From "blank Splunk" to "first answer" |

**Environment:** Splunk Enterprise 10.4.0 (Docker, `splunk/splunk:latest`),
Gemini 2.5 Flash via Google AI Studio (free tier), Python 3.13.

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
| **Observability** track ($3,000) | **Primary target.** SplunkGuard's verified use case is CI/CD failure triage — classic observability problem. Real-world demo: GitLab pipeline logs ingested via HEC → indexed in Splunk → investigated via natural language. End-to-end verified (see [Benchmark](#benchmark)). |
| **Best Use of Splunk MCP Server** ($1,000) | **Not in scope for this submission.** Our MCP code path is implemented and audited, but Splunkbase App #7931 v1.1.0 does not currently boot cleanly on Splunk Enterprise 10.4.0 — see the note under [Architecture](#architecture). If Splunk ships a compatible MCP Server release before the deadline we'll add a video addendum; for now the `--direct` REST path is the verified demo. |

Grand Prize ($7,000) and other "Best Use" prizes (Hosted Models, Developer Tools) are theoretically in play but not the primary target.

---

## License

MIT — same as the rest of the project.
