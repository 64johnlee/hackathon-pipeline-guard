# AgentHack Demo Video — Script & Shot List (~3:00)

> Target: UiPath AgentHack Track 1 (Maestro Case). Judges score: tech implementation,
> design, impact, idea. Show the **case lifecycle** and the **human gate** — that's
> what this track is about. Record at 1080p, narrate over screen capture.

## Prep checklist (before recording)

- [ ] UiPath Labs org (`hackathon26_619`) open in one window: Maestro case board + Action Center
- [ ] GitLab demo project open: a pipeline you can intentionally break (e.g. push a failing test)
- [ ] Orchestrator → Jobs view (to show the triggered process)
- [ ] The GitLab MR page (to show the posted fix at the end)
- [ ] Terminal hidden — everything happens in product UIs, no code on screen until the repo shot

## Script

### 0:00–0:20 — Hook (GitLab, red pipeline on screen)

> "This pipeline just failed. Normally someone copies logs into a chat and spends
> twenty minutes digging. Watch what happens instead — and notice that no fix will
> touch this repo without a human approving it."

### 0:20–0:45 — Architecture (one slide, keep it up 25 seconds max)

> "PipelineGuard wires GitLab into UiPath Maestro. The failure webhook starts an
> Orchestrator process. Gemini 2.5 Flash diagnoses the logs on Cloud Run in about
> 46 seconds. Maestro tracks the incident as a case — Open, AI Diagnosing, Human
> Review, Fix Applied, Closed — and Action Center is where a human says yes or no."

### 0:45–2:15 — Live demo (the core; one continuous take if possible)

1. **(0:45)** Push the breaking commit → pipeline goes red in GitLab
   > "I'll break the build on purpose."
2. **(1:00)** Orchestrator Jobs view: PipelineGuardMaestro starts automatically
   > "The webhook fired — no human kicked this off."
3. **(1:15)** Maestro case board: case appears in *AI Diagnosing*
   > "The case is live. Gemini is reading the failed job logs right now through MCP tools."
4. **(1:35)** Case moves to *Human Review* → open Action Center task: show root cause + the unified diff side by side
   > "Here's the part that matters: a real diff, not a paragraph of AI prose.
   > I can see exactly what will be posted before I approve it."
5. **(1:55)** Click **Approve** → case moves to *Fix Applied*
6. **(2:05)** GitLab MR: the fix comment appears
   > "And the fix lands where developers already work — on the merge request."

### 2:15–2:45 — Why it's different (case board full-screen)

> "Every incident leaves a complete audit trail: who approved, what was proposed,
> when each stage happened. The AI supplies judgment; the Maestro case supplies
> accountability. That's the pattern enterprises actually need to ship AI agents."

### 2:45–3:00 — Close (repo page)

> "Open source, 70 automated tests, and a setup guide that gets you running in
> twenty minutes. PipelineGuard — built with Gemini, Cloud Run, and UiPath Maestro."

## Recording notes

- If the live Gemini diagnosis is slow on camera, cut the wait with a "46 seconds later" jump cut — judges expect edits.
- Keep cursor movement slow; zoom (Ctrl+scroll) on the Action Center diff.
- Upload unlisted to the same YouTube channel as the Google-hackathon video, then paste the link into Devpost → Project Details → "Video demo link".
