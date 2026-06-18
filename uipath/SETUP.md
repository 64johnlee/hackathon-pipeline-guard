# UiPath Automation Cloud — Setup Guide

> Get PipelineGuard Maestro running in ~20 minutes.

## Prerequisites

| | |
|---|---|
| UiPath Automation Cloud account | free at cloud.uipath.com |
| UiPath Studio Web | included in Automation Cloud |
| GitLab account + PAT | `api` + `read_repository` scopes |
| PipelineGuard Cloud Run URL | `https://pipeline-guard-fpgq3ij7ya-uc.a.run.app` |

---

## Step 1 — Create UiPath Automation Cloud Account

1. Go to **https://cloud.uipath.com** → Sign up (free tier is sufficient)
2. Create a new Tenant (e.g. `pipelineguard-demo`)
3. Note your **Orchestrator URL** — typically:
   `https://cloud.uipath.com/{your-org}/{your-tenant}/orchestrator_`

---

## Step 2 — Import the Studio Web Project

1. Automation Cloud → open **Studio Web**
2. Click **New Project** → **Import / Upload**
3. Upload the `uipath/` folder from this repo (or point to the GitHub URL)
4. Studio Web resolves dependencies automatically:
   - `UiPath.System.Activities` 24.10+
   - `UiPath.WebAPI.Activities` 1.14+
   - `UiPath.Persistence.Activities` 1.5+

---

## Step 3 — Configure Orchestrator Assets

Orchestrator → **Assets** → create:

| Asset Name | Type | Value |
|---|---|---|
| `PipelineGuardApiUrl` | Text | `https://pipeline-guard-fpgq3ij7ya-uc.a.run.app` |
| `OrchestratorUrl` | Text | your Orchestrator URL from Step 1 |
| `FolderPath` | Text | `Default` |
| `OrchestratorToken` | Credential | generate below |

To generate the Orchestrator token:
1. Orchestrator → **Tenant Settings** → **API Access**
2. Click **Generate** under "User Key"
3. Paste value into the `OrchestratorToken` credential asset

---

## Step 4 — Configure Maestro Case Definition

1. Automation Cloud → **Maestro** → **Case Catalogs** → **New Catalog**
2. Name: `Pipeline Failure Incident`
3. Stages: `Open` → `AI Diagnosing` → `Human Review` → `Fix Applied` → `Closed`
4. Data fields:
   - `project` (Text)
   - `pipeline_id` (Text)
   - `branch` (Text)
   - `root_cause` (Long Text)
   - `failure_category` (Text)
   - `full_diagnosis` (Long Text)
5. Save and publish

---

## Step 5 — Publish and Deploy

1. Studio Web → **Publish** to your Orchestrator tenant
2. Orchestrator → **Processes** → **Add Process** → select `PipelineGuardMaestro`
3. Orchestrator → **Triggers** → **API Trigger** → create trigger on the process
4. Copy the **API Trigger URL**

---

### Optional — let Cloud Run trigger the process (OAuth2)

Instead of pointing GitLab directly at UiPath, the Cloud Run webhook can start the
Maestro process itself. Create the credentials once:

1. Automation Cloud → **Admin** → **External Applications** → **Add application** (Confidential)
2. Scopes: `OR.Jobs` `OR.Jobs.Execute` · Grant type: **Client Credentials**
3. Set on the Cloud Run service: `UIPATH_TRIGGER_URL` (from Step 5), plus
   `UIPATH_CLIENT_ID` + `UIPATH_CLIENT_SECRET` (auto-refreshing token) **or** a
   static `UIPATH_TOKEN`

If the trigger call fails, the webhook falls back to local diagnosis — pipeline
failures are never dropped.

---

## Step 6 — Connect GitLab Webhook

In GitLab: **Settings → Webhooks** → add the API Trigger URL → enable **Pipeline events**.

GitLab sends the raw pipeline JSON directly to UiPath on every failure. UiPath starts `Main.xaml` with the payload as `WebhookPayload`.

---

## Step 7 — Test End-to-End

```bash
# Manually trigger a test approval
curl -X POST https://pipeline-guard-fpgq3ij7ya-uc.a.run.app/api/uipath/callback \
  -H "Content-Type: application/json" \
  -d '{"case_id":"test-001","action":"approve","project":"demo","pipeline_id":0,"fix_diff":""}'
```

Full flow:
1. GitLab pipeline fails → webhook fires
2. Orchestrator job starts → `Main.xaml` runs
3. `DiagnoseWithAI.xaml` calls Cloud Run → Gemini diagnoses in ~46 s
4. `CreateMaestroCase.xaml` opens a Maestro Case
5. `HumanReview.xaml` creates an Action Center task
6. Engineer clicks **Approve Fix** in UiPath Action Center
7. `PostApprovedFix.xaml` calls `/api/uipath/callback` → fix posted to GitLab MR

---

## Architecture

```
GitLab pipeline failure
        │ webhook POST
        ▼
UiPath Orchestrator API Trigger
        │ starts process
        ▼
PipelineGuardMaestro / Main.xaml
  ├─ DiagnoseWithAI.xaml      POST /api/diagnose        Gemini 2.5 Flash
  ├─ CreateMaestroCase.xaml   POST /odata/Cases          Orchestrator Maestro
  ├─ HumanReview.xaml         POST+poll /tasks           Action Center
  └─ PostApprovedFix.xaml     POST /api/uipath/callback  GitLab MR comment
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| HTTP 401 on Orchestrator | Regenerate token, update Credential asset |
| Case not in Maestro | Confirm Catalog name is `Pipeline Failure Incident` |
| Task missing in Action Center | Check folder path Asset matches Orchestrator folder |
| `/api/diagnose` returns 500 | Check Cloud Run logs for missing GEMINI_API_KEY |
| Workflow stuck at HumanReview | Timeout is 4 h; complete task manually in Action Center |
