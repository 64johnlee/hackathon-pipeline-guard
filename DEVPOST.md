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
