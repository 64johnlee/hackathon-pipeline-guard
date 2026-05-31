# PipelineGuard — Devpost Submission Copy

> Submission text for the [Google Cloud Rapid Agent Hackathon](https://rapid-agent.devpost.com) (GitLab track).
> Each section maps to a standard Devpost field. Verify the benchmark numbers reflect your latest run before submitting.

## Tagline
An AI agent that watches your GitLab CI, and the moment a pipeline fails, tells you the exact root cause and hands you a diff-ready fix — in seconds, with zero clicks.

## Inspiration
Every engineer knows the ritual: a pipeline goes red, you open the job, scroll through hundreds of log lines, and eventually find the one line that matters — a missing env var, a dependency conflict, a flaky test. It's tedious, it's interrupt-driven, and it scales terribly across a team. We wanted an agent that does the scrolling for us: reads the logs the way a senior engineer would, isolates the *actual* cause (not "build failed"), and proposes the fix as a patch you can apply immediately.

## What it does
PipelineGuard is a Gemini-powered agent that auto-diagnoses GitLab CI pipeline failures. Register it once as a GitLab Pipeline webhook and, on every failure, it:

1. **Fetches** the pipeline, its jobs, and the failing job logs through MCP tools.
2. **Reasons** over them with **Gemini 2.5 Flash** in an agentic tool-call loop — it decides which tools to call and when it has enough context.
3. **Produces** a structured diagnosis: the precise **root cause**, a **failure category** (env / dependency / flaky / code / config…), and one or more **fix proposals as unified diffs** with high/medium/low confidence.
4. **Comments** the findings directly on the associated merge request, so the whole team sees them instantly.

There's also a live **`/demo`** endpoint for read-only, on-demand diagnosis of any public pipeline, and a companion **SplunkGuard** agent that runs natural-language investigations over historical pipeline failures via the official Splunk MCP Server.

## How we built it
The core is a **dual-MCP architecture** that lets Gemini talk to GitLab through clean, typed tools instead of brittle prompt-parsing:

- **A purpose-built MCP server** (`pipelineguard.mcp_server`, stdio) exposing 5 GitLab tools: `list_pipelines`, `get_pipeline_jobs`, `get_job_log`, `find_merge_request_by_sha`, `create_merge_request_note`.
- **The official GitLab MCP server** (Streamable HTTP, `gl_` tool prefix) for broader project/MR access.

The agent routes tool calls by name prefix, runs a bounded loop (≤15 iterations, with a safety cap that's never hit in practice), and returns a Pydantic-validated `DiagnosticReport`. It's wrapped in a **FastAPI** webhook server (`/webhook/gitlab`, `/demo`, `/health`), containerized, and deployed live. Inference runs on **Gemini 2.5 Flash** via Google AI Studio or **Vertex AI**, and it deploys to **Google Cloud Run** (scale-to-zero) with one command.

## Accomplishments we're proud of
We didn't just demo it on a toy repo — we ran it **end-to-end against a real failed pipeline in `gitlab-org/cli`** (pipeline #2552952663). The agent identified the correct root cause (a config error — a malformed git ref) in **~46 seconds using just 2 tool calls**, terminating the loop far under its safety cap. It's **read-only on your repository** (it proposes, it doesn't push), and it's **live right now** — anyone can hit the deployed Space and run a diagnosis.

## Challenges we ran into
- **Reliable structured output from an LLM**: Gemini occasionally wrapped JSON in backticks or embedded literal control characters inside diff payloads. We built a robust extractor (brace-counting + control-char sanitization) so a model quirk never breaks a diagnosis.
- **MCP transport plumbing**: reconciling stdio and Streamable HTTP MCP backends — and surviving `anyio` exception-group behavior — took careful error handling (catching `BaseException` groups, unwrapping nested errors) to keep the agent loop resilient.
- **Knowing when to stop**: an agent that keeps calling tools forever is useless. Tuning the loop so it gathers exactly the context it needs (and no more) is what gets us to 2 tool calls instead of 10.

## What we learned
Giving the model *typed tools* via MCP beats stuffing raw logs into a prompt — the agent stays grounded, calls fewer tools, and produces cleaner diagnoses. And designing for **agent termination** is as important as designing the tools themselves.

## What's next
Auto-open MRs with the proposed fix (behind a human-approval gate), learn per-project failure patterns over time, expand beyond GitLab to GitHub Actions, and deepen the SplunkGuard analytics loop for fleet-wide failure trends.

## Built with
`Gemini 2.5 Flash` · `Vertex AI` · `GitLab MCP Server` · `Model Context Protocol` · `FastAPI` · `python-gitlab` · `Pydantic v2` · `google-genai SDK` · `Google Cloud Run` · `Splunk HEC` · `Docker`

## Links
- **Live app:** https://johnlee007-pipelineguard.hf.space
- **GitHub:** https://github.com/64johnlee/hackathon-pipeline-guard

## Demo video

> The video demonstrates an illustrative failure scenario (a missing `REDIS_URL`) to show the full loop clearly. The real-world end-to-end verification against `gitlab-org/cli` (~46s, 2 tool calls) is documented in the README — don't conflate the two in the writeup.

**Short caption (video gallery tile):**
PipelineGuard: a GitLab pipeline fails, and Gemini 2.5 Flash diagnoses the exact root cause through a live MCP tool-call loop, then posts a diff-ready fix to the merge request — in ~90 seconds, zero clicks.

**Full description:**
PipelineGuard watches your GitLab CI. When a pipeline fails, a Gemini 2.5 Flash agent reads the logs through MCP tools, pinpoints the root cause, proposes a unified-diff fix, and comments it on the merge request. This ~90-second walkthrough shows the full agentic loop running against a failed pipeline.

What you'll see:
- One command kicks it off — no dashboards, no manual log-scrolling
- A **dual-MCP architecture** connecting: the official GitLab MCP server (`gitlab.com/api/v4/mcp`) and PipelineGuard's bundled stdio MCP server
- Gemini autonomously working a tool-call loop (≤15 iterations) — discover project → find the failed pipeline → enumerate jobs → pull the failing job log
- A precise diagnosis: a missing `REDIS_URL` env var causing a `ConnectionError`
- A proposed fix as a unified diff on `.gitlab-ci.yml` (confidence: high), posted as a comment on the merge request
- The architecture recap and the live deployed app

Try it live: https://johnlee007-pipelineguard.hf.space
Built for the Google Cloud Rapid Agent Hackathon — GitLab track.
Code (MIT): https://github.com/64johnlee/hackathon-pipeline-guard

**Chapters** *(approximate — verify against the final cut; total ≈ 1:27):*
- `0:00` Title — PipelineGuard
- `0:05` The problem: a red pipeline, and the log-scrolling ritual
- `0:11` One command kicks off the agent
- `0:14` Dual MCP connected (official GitLab MCP + bundled PipelineGuard MCP)
- `0:18` Iteration 1 — discover the project
- `0:23` Iteration 2 — find the failed pipeline
- `0:28` Iteration 3 — enumerate the jobs
- `0:33` Iteration 4 — pull the failing job log
- `0:39` Diagnosis: missing `REDIS_URL` → `ConnectionError`
- `0:49` Proposed fix diff + MR comment posted
- `1:01` Architecture: dual MCP, Gemini 2.5 Flash, ≤15 iterations
- `1:16` Try it live — deployed HF Space

**Tags:** `gemini` · `mcp` · `gitlab-ci` · `ai-agent` · `devops` · `ci-cd` · `root-cause-analysis` · `google-cloud`
