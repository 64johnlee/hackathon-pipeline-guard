# PipelineGuard → Maestro BPMN Mapping

How the five XAML workflows map onto a UiPath Maestro **BPMN process** (the
"Maestro Case" deliverable). Model this in UiPath Studio's Maestro/agentic-process
designer. In Maestro the **process instance _is_ the case** — the process data model
below is the case's data, so there is no separate "create case" REST call needed
(the original `CreateMaestroCase.xaml` becomes optional; see Task C).

---

## Process data model (case fields)

Define these as process variables on the Maestro process. They are the case's
tracked data (same fields the issue/SETUP.md call for):

| Variable | Type | Set by | Notes |
|---|---|---|---|
| `webhookPayload` | String | Start event | raw GitLab webhook JSON |
| `project` | String | Task A | `path_with_namespace` |
| `pipelineId` | String | Task A | `object_attributes.id` |
| `branch` | String | Task A | `object_attributes.ref` (default "unknown") |
| `diagnosisJson` | String | Task B | full `/api/diagnose` response |
| `rootCause` | String | Task B′ | `diagnosisJson.root_cause` |
| `failureCategory` | String | Task B′ | `diagnosisJson.failure_category` |
| `fixDiff` | String | Task B′ | `diagnosisJson.fix_proposals[0].diff` |
| `caseId` | String | Task C (or process instance id) | |
| `isApproved` | Boolean | Task D | from Action Center action |
| `resultMessage` | String | Task E | callback result |

Stage/status labels for the case lifecycle (set on transitions):
`Open → AI Diagnosing → Human Review → Fix Applied / Rejected → Closed`.

Config inputs come from the Orchestrator **Assets** already created in the Shared
folder: `PipelineGuardApiUrl`, `OrchestratorUrl`, `FolderPath`, `OrchestratorToken`.

---

## BPMN flow

```
(Message Start: GitLab webhook)
        │  webhookPayload
        ▼
[A] Script Task — Parse GitLab payload
        │  project, pipelineId, branch
        ▼
[B] Service Task (HTTP) — AI Diagnosis      POST {PipelineGuardApiUrl}/api/diagnose
        │  diagnosisJson
        ▼
[B′] Script Task — Extract fields           rootCause, failureCategory, fixDiff
        │
        ▼
[C] (optional) Service Task (HTTP) — Create Case record   POST {OrchestratorUrl}/odata/Cases
        │  caseId   ← or use the Maestro process instance id
        ▼
[D] User Task (Action Center) — Human review   actions: Approve Fix / Reject Fix
        │  isApproved
        ▼
   ◇ Exclusive Gateway — isApproved?
   ├── true ──► [E] Service Task (HTTP) — Post fix   POST {PipelineGuardApiUrl}/api/uipath/callback
   │                    │  resultMessage
   │                    ▼
   │              (End: Fix Applied)
   └── false ─► (End: Rejected)
```

---

## Element-by-element spec

### Start Event — Message (GitLab webhook)
- Trigger type: **Message/HTTP start** (wired to the Orchestrator API trigger that the
  GitLab webhook calls). Payload → `webhookPayload`.

### [A] Script Task — "Parse GitLab payload"  *(from Main.xaml step 1)*
Parse `webhookPayload` JSON and set:
- `project        = payload.project.path_with_namespace`
- `pipelineId     = payload.object_attributes.id`
- `branch         = payload.object_attributes.ref ?? "unknown"`

### [B] Service Task (HTTP Request) — "AI Diagnosis"  *(DiagnoseWithAI.xaml)*
- **Method**: POST
- **URL**: `{PipelineGuardApiUrl}/api/diagnose`
- **Headers**: `Content-Type: application/json`, `Accept: application/json`
- **Body**: `{"project":"{project}","pipeline_id":{pipelineId}}`
- **Output**: response body → `diagnosisJson`
- **Error**: non-2xx → throw / route to an error end event.

### [B′] Script Task — "Extract diagnosis fields"  *(shared by CreateCase/HumanReview/PostFix)*
From `diagnosisJson`:
- `rootCause       = root_cause ?? "unknown"`
- `failureCategory = failure_category ?? "unknown"`
- `fixDiff         = fix_proposals[0].diff ?? "(no fix proposed)"`

### [C] Service Task (HTTP) — "Create Case record"  *(CreateMaestroCase.xaml — OPTIONAL)*
Only needed if you also want an Orchestrator **Cases** record separate from the Maestro
process instance. Otherwise skip and use the process instance id as `caseId`.
- **Method**: POST   **URL**: `{OrchestratorUrl}/odata/Cases`
- **Headers**: `Content-Type/Accept: application/json`, `Authorization: Bearer {OrchestratorToken}`,
  `X-UIPATH-OrganizationUnitId: {FolderPath}`
- **Body**:
  ```json
  {"title":"[PipelineGuard] {project} ({branch}) — {failureCategory}",
   "priority":"High","status":"Open","source":"PipelineGuard-GitLabCI",
   "data":{"project":"{project}","pipeline_id":"{pipelineId}","branch":"{branch}",
           "root_cause":"{rootCause}","failure_category":"{failureCategory}",
           "full_diagnosis":"{diagnosisJson}"}}
  ```
- **Output**: `caseId = response.Id ?? response.id`

### [D] User Task (Action Center) — "Human review"  *(HumanReview.xaml)*
- **Type**: Action Center **Form/Approval** task (BPMN-native — replaces the manual
  POST /tasks + 480× polling loop; Maestro suspends the case until the task completes).
- **Title**: `Review AI fix for {project} (case {caseId})`
- **Display**: rootCause, fixDiff, caseId.
- **Actions/outcomes**: `Approve Fix`, `Reject Fix`.
- **Output**: `isApproved = (chosen action contains "approve")`.
- Persistence: this is the long-running wait — Maestro handles it natively, no polling.

### ◇ Exclusive Gateway — "Approved?"
- Condition: `isApproved == true` → [E]; else → End (Rejected).

### [E] Service Task (HTTP) — "Post approved fix"  *(PostApprovedFix.xaml)*
- **Method**: POST   **URL**: `{PipelineGuardApiUrl}/api/uipath/callback`
- **Headers**: `Content-Type/Accept: application/json`
- **Body**:
  ```json
  {"case_id":"{caseId}","action":"approve","project":"{project}",
   "pipeline_id":{pipelineId},"fix_diff":"{fixDiff}"}
  ```
- **Output**: `resultMessage = response.status ?? "ok"` (or `callback_error_http_{code}` on non-2xx)
- Then transition case → **Fix Applied** → End.

### End Events
- **Fix Applied** (approved path) · **Rejected** (rejected path) · optional **Error** (diagnosis/case failure).

---

## What changes vs the XAML

| XAML element | BPMN element | Why |
|---|---|---|
| `Main.xaml` Sequence | The BPMN process itself | the process orchestrates the flow |
| InvokeCode (JSON parse) | Script Task | same VB/expression logic |
| `DiagnoseWithAI` / `PostApprovedFix` HTTPRequest | Service Task (HTTP connector) | direct equivalent |
| `CreateMaestroCase` REST POST | optional Service Task **or** native case instance | the process instance is the case |
| `HumanReview` POST + 480× poll loop | single **User Task** (Action Center) | Maestro suspends natively — no polling |
| `If isApproved` | Exclusive Gateway | direct equivalent |

The agentic value (Gemini diagnosis, human-in-the-loop approval, GitLab write-back)
is preserved exactly; only the human-wait and the case creation become BPMN-native
instead of hand-rolled REST + polling.

---

## Appendix A — Script Task expressions (JSON parse)

The XAML used VB `InvokeCode` blocks with Newtonsoft. In a VB-based Studio project
(this one is `studioVersion 24.10`, VB), drop the same one-liners into each Script Task.
`JObject`/`JArray` are available via `Newtonsoft.Json.Linq`.

**[A] Parse GitLab payload** — in: `webhookPayload` → out: `project`, `pipelineId`, `branch`
```vb
Dim payload = Newtonsoft.Json.Linq.JObject.Parse(webhookPayload)
project    = payload("project")("path_with_namespace").ToString()
pipelineId = payload("object_attributes")("id").ToString()
branch     = If(payload("object_attributes")("ref") IsNot Nothing, payload("object_attributes")("ref").ToString(), "unknown")
```

**[B′] Extract diagnosis fields** — in: `diagnosisJson` → out: `rootCause`, `failureCategory`, `fixDiff`
```vb
Dim diag = Newtonsoft.Json.Linq.JObject.Parse(diagnosisJson)
rootCause       = If(diag("root_cause")       IsNot Nothing, diag("root_cause").ToString(),       "unknown")
failureCategory = If(diag("failure_category") IsNot Nothing, diag("failure_category").ToString(), "unknown")
Dim fps = diag("fix_proposals")
fixDiff = If(fps IsNot Nothing AndAlso fps.HasValues AndAlso fps(0)("diff") IsNot Nothing, fps(0)("diff").ToString(), "(no fix proposed)")
```

**[C] caseId from /odata/Cases response** (only if you keep Task C)
```vb
Dim resp = Newtonsoft.Json.Linq.JObject.Parse(responseBody)
caseId = If(resp("Id") IsNot Nothing, resp("Id").ToString(), If(resp("id") IsNot Nothing, resp("id").ToString(), "unknown"))
```

**[E] resultMessage from callback response**
```vb
resultMessage = If(statusCode < 200 OrElse statusCode >= 300, "callback_error_http_" & statusCode.ToString(), _
                   If(Newtonsoft.Json.Linq.JObject.Parse(responseBody)("status") IsNot Nothing, _
                      Newtonsoft.Json.Linq.JObject.Parse(responseBody)("status").ToString(), "ok"))
```

If the Maestro modeler exposes a JSONPath expression builder instead of VB, the paths
are: `$.project.path_with_namespace`, `$.object_attributes.id`, `$.object_attributes.ref`,
`$.root_cause`, `$.failure_category`, `$.fix_proposals[0].diff`, `$.Id`/`$.id`, `$.status`.

---

## Appendix B — Action Center form for Task D (Human review)

Configure the User Task's form with these fields:

| Field | Type | Value / binding |
|---|---|---|
| Title | label | `Review AI fix for {project} (case {caseId})` |
| Root cause | read-only text | `{rootCause}` |
| Proposed fix (unified diff) | read-only multi-line / code | `{fixDiff}` |
| Case ID | read-only text | `{caseId}` |
| — outcome — | two submit buttons | **Approve Fix** / **Reject Fix** |

Outcome → process variable:
```
isApproved = (selectedAction.ToLower().Contains("approve"))
```
Wire the gateway on `isApproved`. No timeout/polling needed — the Maestro process
suspends on this task and resumes when the engineer submits (the XAML's 4-hour,
480-poll loop is replaced entirely by this single suspend/resume).
