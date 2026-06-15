#!/usr/bin/env bash
# Deploy PipelineGuard webhook server to Google Cloud Run.
#
# Prerequisites:
#   gcloud auth login && gcloud auth application-default login
#   gcloud config set project YOUR_PROJECT
#
# Usage:
#   export GCP_PROJECT=my-project
#   export GITLAB_TOKEN=glpat-...
#   bash deploy_cloudrun.sh
#
# Optional env vars:
#   GCP_LOCATION     (default: us-central1)
#   SERVICE_NAME     (default: pipeline-guard)
#   GEMINI_API_KEY   — use AI Studio instead of Vertex AI
#   WEBHOOK_SECRET   — GitLab webhook token for request validation
#   PG_KB_DATASTORE  (default: pipelineguard-kb) — Vertex AI Search data store for RAG grounding
#   PG_KB_LOCATION   (default: global)
#
# This script is safe to re-run: it uses --update-env-vars / --update-secrets so
# values set outside it (e.g. UiPath config) are preserved, and it verifies the
# new revision is healthy before declaring success.

set -euo pipefail

# Clear, located failure message instead of a bare nonzero exit.
trap 'echo "ERROR: deploy failed at line ${LINENO} (exit $?)" >&2' ERR

# --- Preflight: required tooling + active credentials --------------------------
command -v gcloud >/dev/null 2>&1 \
    || { echo "ERROR: gcloud CLI not found on PATH." >&2; exit 1; }
ACTIVE_ACCT=$(gcloud auth list --filter=status:ACTIVE --format='value(account)' 2>/dev/null)
[[ -n "${ACTIVE_ACCT}" ]] \
    || { echo "ERROR: no active gcloud account. Run: gcloud auth login" >&2; exit 1; }

PROJECT="${GCP_PROJECT:?Set GCP_PROJECT}"
REGION="${GCP_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-pipeline-guard}"
REPO="pipelineguard"

# Confirm the project is reachable with the active credentials.
gcloud projects describe "${PROJECT}" >/dev/null 2>&1 \
    || { echo "ERROR: cannot access project '${PROJECT}' as ${ACTIVE_ACCT}." >&2; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# --- Immutable, rollback-able image tag (git SHA, else timestamp) --------------
if GIT_SHA=$(git -C "${SCRIPT_DIR}" rev-parse --short HEAD 2>/dev/null); then
    [[ -n "$(git -C "${SCRIPT_DIR}" status --porcelain 2>/dev/null)" ]] && GIT_SHA="${GIT_SHA}-dirty"
    TAG="${GIT_SHA}"
else
    TAG="$(date +%Y%m%d-%H%M%S)"
fi
IMAGE_BASE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}"
IMAGE="${IMAGE_BASE}:${TAG}"
IMAGE_LATEST="${IMAGE_BASE}:latest"

echo "==> Project:  ${PROJECT}"
echo "==> Account:  ${ACTIVE_ACCT}"
echo "==> Region:   ${REGION}"
echo "==> Service:  ${SERVICE}"
echo "==> Image:    ${IMAGE}"
echo ""

# 0. Enable required Google Cloud APIs (idempotent)
echo "==> Enabling required Google Cloud APIs..."
gcloud services enable \
    run.googleapis.com cloudbuild.googleapis.com \
    artifactregistry.googleapis.com secretmanager.googleapis.com \
    aiplatform.googleapis.com discoveryengine.googleapis.com firestore.googleapis.com \
    --project "${PROJECT}"

# 1. Create Artifact Registry repo (idempotent)
echo "==> Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --quiet 2>/dev/null || true

# 1b. Never ship secrets or junk to Cloud Build.
if [[ ! -f "${SCRIPT_DIR}/.gcloudignore" ]]; then
    echo "==> No .gcloudignore found — creating one so secrets aren't uploaded to Cloud Build..."
    cat > "${SCRIPT_DIR}/.gcloudignore" <<'IGN'
.git/
.env
.env.*
*.key
*.pem
*.crt
__pycache__/
.venv/
venv/
.pytest_cache/
.ruff_cache/
*.log
IGN
fi

# 2. Build immutable image via Cloud Build, then alias :latest for convenience
echo "==> Building container image with Cloud Build..."
gcloud builds submit \
    --tag "${IMAGE}" \
    --project "${PROJECT}" \
    "${SCRIPT_DIR}"
echo "==> Aliasing ${IMAGE} as :latest..."
gcloud artifacts docker tags add "${IMAGE}" "${IMAGE_LATEST}" --quiet 2>/dev/null || true

# 3. Build env-var list. PG_KB_DATASTORE enables RAG grounding via Vertex AI Search.
ENV_VARS="GCP_PROJECT=${PROJECT},GCP_LOCATION=${REGION}"
ENV_VARS="${ENV_VARS},PG_KB_DATASTORE=${PG_KB_DATASTORE:-pipelineguard-kb}"
ENV_VARS="${ENV_VARS},PG_KB_LOCATION=${PG_KB_LOCATION:-global}"
UPDATE_SECRETS=""

# Store a secret in Secret Manager (idempotent) and queue it for binding.
store_secret() {
    local name="$1" val="$2"
    [[ -z "${val}" ]] && return 0
    echo "==> Storing ${name} in Secret Manager..."
    printf '%s' "${val}" | gcloud secrets create "${name}" \
        --data-file=- --project="${PROJECT}" 2>/dev/null \
      || printf '%s' "${val}" | gcloud secrets versions add "${name}" \
        --data-file=- --project="${PROJECT}" >/dev/null
    UPDATE_SECRETS="${UPDATE_SECRETS:+${UPDATE_SECRETS},}${name}=${name}:latest"
}

store_secret GITLAB_TOKEN "${GITLAB_TOKEN:-}"
store_secret GEMINI_API_KEY "${GEMINI_API_KEY:-}"
store_secret WEBHOOK_SECRET "${WEBHOOK_SECRET:-}"

# 3b. Grant the Cloud Run runtime service account read access to the secrets above
# (default compute SA). Without this, deploy succeeds but requests 500 on secret reads.
if [[ -n "${UPDATE_SECRETS}" ]]; then
    echo "==> Granting secretmanager.secretAccessor to the runtime service account..."
    PNUM=$(gcloud projects describe "${PROJECT}" --format='value(projectNumber)')
    gcloud projects add-iam-policy-binding "${PROJECT}" \
        --member "serviceAccount:${PNUM}-compute@developer.gserviceaccount.com" \
        --role roles/secretmanager.secretAccessor \
        --condition=None --quiet >/dev/null \
      || echo "WARN: could not grant secretAccessor automatically — if requests 500, grant it manually."
fi

# Use Vertex AI if no GEMINI_API_KEY provided.
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    ENV_VARS="${ENV_VARS},VERTEX_FLAG=--vertex --gcp-project ${PROJECT}"
fi

# 3c. Warn (don't fail) if the KB data store is missing — otherwise diagnoses run
# ungrounded with no visible signal.
KB_DS="${PG_KB_DATASTORE:-pipelineguard-kb}"
KB_LOC="${PG_KB_LOCATION:-global}"
if command -v curl >/dev/null 2>&1; then
    TOKEN=$(gcloud auth print-access-token 2>/dev/null || true)
    if [[ -n "${TOKEN}" ]]; then
        DS_URL="https://discoveryengine.googleapis.com/v1/projects/${PROJECT}/locations/${KB_LOC}/collections/default_collection/dataStores/${KB_DS}"
        DS_CODE=$(curl -s -o /dev/null -w '%{http_code}' -H "Authorization: Bearer ${TOKEN}" "${DS_URL}" || echo 000)
        if [[ "${DS_CODE}" == "200" ]]; then
            echo "==> KB data store '${KB_DS}' (${KB_LOC}) verified."
        else
            echo "WARN: Vertex AI Search data store '${KB_DS}' (${KB_LOC}) not found (HTTP ${DS_CODE})"
            echo "      — diagnoses will run UNGROUNDED until it exists."
        fi
    fi
fi

# 4. Deploy to Cloud Run. --update-* preserves env vars / secrets set outside this
# script (e.g. UiPath config) instead of wiping them.
echo "==> Deploying to Cloud Run..."
DEPLOY_CMD=(
    gcloud run deploy "${SERVICE}"
    --image "${IMAGE}"
    --platform managed
    --region "${REGION}"
    --project "${PROJECT}"
    --allow-unauthenticated
    --memory 512Mi
    --min-instances 0
    --max-instances 5
    --timeout 300
    --quiet
    --update-env-vars "${ENV_VARS}"
)

if [[ -n "${UPDATE_SECRETS}" ]]; then
    DEPLOY_CMD+=(--update-secrets "${UPDATE_SECRETS}")
fi

"${DEPLOY_CMD[@]}"

# 5. Resolve URL + the revision that was just rolled out.
URL=$(gcloud run services describe "${SERVICE}" \
    --platform managed --region "${REGION}" --project "${PROJECT}" \
    --format "value(status.url)")
REV=$(gcloud run services describe "${SERVICE}" \
    --platform managed --region "${REGION}" --project "${PROJECT}" \
    --format "value(status.latestReadyRevisionName)")

# 6. Verify the new revision actually serves traffic before declaring success.
# Skip (with a warning) rather than false-fail if curl isn't available locally.
if command -v curl >/dev/null 2>&1; then
    echo "==> Verifying ${URL}/health ..."
    HEALTHY=""
    for _ in 1 2 3 4 5 6 7 8 9 10; do
        HC=$(curl -s -o /dev/null -w '%{http_code}' "${URL}/health" || echo 000)
        if [[ "${HC}" == "200" ]]; then HEALTHY="yes"; break; fi
        sleep 3
    done
    if [[ -z "${HEALTHY}" ]]; then
        trap - ERR
        echo "ERROR: ${SERVICE} deployed (rev ${REV}) but /health never returned 200." >&2
        echo "       Roll back with: gcloud run services update-traffic ${SERVICE} --region ${REGION} --to-revisions PREVIOUS=100" >&2
        exit 1
    fi
else
    echo "WARN: curl not found — skipping /health verification. Check ${URL}/health manually."
fi

echo ""
echo "======================================================"
echo "  PipelineGuard deployed & healthy!"
echo "  Revision: ${REV}"
echo "  Image:    ${IMAGE}"
echo "  URL:      ${URL}"
echo "  Webhook:  ${URL}/webhook/gitlab"
echo "  Health:   ${URL}/health"
echo "======================================================"
echo ""
echo "Configure GitLab webhook:"
echo "  Settings -> Webhooks -> URL: ${URL}/webhook/gitlab"
echo "  Trigger: Pipeline events"
if [[ -n "${WEBHOOK_SECRET:-}" ]]; then
    echo "  Secret token: (use your WEBHOOK_SECRET value)"
fi
