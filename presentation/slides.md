# PipelineGuard × UiPath Maestro
## DevOps Incident Management — Presentation Deck

> **UiPath AgentHack 2026 — Track 1: Maestro Case**
> Adapt this content into UiPath's provided slide template before submitting.

---

## SLIDE 1 — Title

**PipelineGuard × UiPath Maestro**
*Every CI failure is a case. Every case gets an AI diagnosis. Every fix needs a human sign-off.*

Track: Maestro Case | June 2026

---

## SLIDE 2 — The Problem

**The ritual every engineer knows:**

1. Pipeline goes red at 2am
2. Open the job, scroll 800 log lines
3. Find the one line that matters
4. Wait for someone with context to notice

**Cost**: $2–5K per incident (senior engineer at $200/hr × 2–4 hours investigation)
**Scale**: millions of GitLab CI pipelines fail every day

No audit trail. No structured lifecycle. No accountability handoff. Just a red badge and an interrupt.

---

## SLIDE 3 — The Insight

**A pipeline failure is a business exception.**

UiPath Maestro Case was built for business exceptions:
- Insurance claims, HR incidents, customer complaints
- Structured lifecycle: Open → Diagnose → Review → Resolve → Close
- Agent + human handoff built in
- Full audit trail

**We are the first team to apply Maestro Case to DevOps incidents.**

---

## SLIDE 4 — Architecture

```
GitLab pipeline fails
        │  webhook
        ▼
UiPath Orchestrator (API Trigger)
        │  starts PipelineGuardMaestro process
        ▼
  Main.xaml orchestrates 4 sub-workflows:

  DiagnoseWithAI.xaml     →  POST /api/diagnose
                          ←  Gemini 2.5 Flash: root cause + fix diff  (~46 s)

  CreateMaestroCase.xaml  →  POST /odata/Cases
                          ←  Maestro Case #ID created

  HumanReview.xaml        →  POST /tasks (Action Center)
                          ←  Engineer: [Approve Fix] / [Reject Fix]

  PostApprovedFix.xaml    →  POST /api/uipath/callback
                          →  GitLab MR comment with unified diff
```

UiPath components: Studio Web · Maestro Case · Action Center · Orchestrator REST · API Trigger · Persistence Activities

---

## SLIDE 5 — Live Demo

**What judges will see:**

1. GitLab pipeline fails → webhook fires to UiPath Orchestrator
2. Gemini 2.5 Flash diagnoses in ~46 s via 2 MCP tool calls
3. **Maestro Case** opens: "Pipeline Failure Incident — myorg/backend (env_var_missing)"
4. **Action Center task** appears: root cause + fix diff + Approve/Reject buttons
5. Engineer clicks **Approve Fix**
6. Fix diff posted as GitLab MR comment — engineer applies in one click

**Try it live**: https://pipeline-guard-fpgq3ij7ya-uc.a.run.app/demo

---

## SLIDE 6 — Benchmarks

| Metric | Value |
|---|---|
| Diagnosis time | ~46 seconds end-to-end |
| Gemini tool calls | 2 (cap is 15) |
| Verified against | `gitlab-org/cli` pipeline #2552952663 |
| Root cause accuracy | Correct (config error: malformed git ref) |
| Cost per diagnosis | < $0.01 |
| Engineering time saved | 2–4 hours per incident |

---

## SLIDE 7 — Platform Usage

| UiPath Component | How used |
|---|---|
| Studio Web | Full workflow built in Studio Web (5 .xaml files) |
| Maestro Case | Case lifecycle for every pipeline failure |
| Action Center | Human-in-the-loop approval gate |
| Orchestrator REST | Case creation + task management |
| API Trigger | GitLab webhook → process start |
| Assets / Credentials | Tokens stored securely |
| Persistence Activities | Survives restart during human review wait |

---

## SLIDE 8 — Why This Wins

1. **Novel domain** — Maestro Case for DevOps is a new category. Judges see HR/finance; we bring CI/CD.
2. **Deep platform usage** — Studio Web + Maestro + Action Center + Orchestrator API + Persistence + Assets.
3. **Production-grade** — real benchmark, live demo URL, MIT license, 20-min setup.
4. **Claude Code bonus (+2 pts)** — full session documented in README.
5. **Cross-platform integration** — GitLab + Gemini + UiPath + Cloud Run = 4 platforms, one workflow.

---

## SLIDE 9 — Business Case

| Tier | Price | Included |
|---|---|---|
| Free | $0 | 3 projects, 100 diagnoses/month |
| Teams | $29/mo | 10 projects, unlimited |
| Business | $99/mo | Unlimited, SLA, UiPath integration |

**ROI**: payback after 1 incident ($400–$800 engineering time saved vs < $0.01 diagnosis cost).

**Market**: $50B+ DevOps tooling. 1% of GitLab orgs at $29/mo = $70M+ ARR.

---

## SLIDE 10 — What's Next

- Auto-open GitLab MRs with fix (approval gate already built)
- Slack notifications from Maestro Case status changes
- Expand to GitHub Actions + Jenkins
- UiPath Marketplace listing
- SplunkGuard integration for observability → remediation closed loop

---

## SLIDE 11 — Built With

UiPath Studio Web · Maestro Case · Action Center · Orchestrator REST · Persistence Activities
Gemini 2.5 Flash · Vertex AI · Model Context Protocol · GitLab MCP Server (official)
Google Cloud Run · Python 3.12 · FastAPI · Claude Code

---

## SLIDE 12 — Links

| | |
|---|---|
| Live app | https://pipeline-guard-fpgq3ij7ya-uc.a.run.app |
| GitHub | https://github.com/64johnlee/hackathon-pipeline-guard |
| Demo video | https://youtu.be/f2g1ppeLhqk |
| UiPath setup | uipath/SETUP.md |
