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
#   GCP_LOCATION    (default: us-central1)
#   SERVICE_NAME    (default: pipeline-guard)
#   GEMINI_API_KEY  — use AI Studio instead of Vertex AI
#   WEBHOOK_SECRET  — GitLab webhook token for request validation

set -euo pipefail

PROJECT="${GCP_PROJECT:?Set GCP_PROJECT}"
REGION="${GCP_LOCATION:-us-central1}"
SERVICE="${SERVICE_NAME:-pipeline-guard}"
REPO="pipelineguard"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT}/${REPO}/${SERVICE}:latest"

echo "==> Project:  ${PROJECT}"
echo "==> Region:   ${REGION}"
echo "==> Service:  ${SERVICE}"
echo "==> Image:    ${IMAGE}"
echo ""

# 1. Create Artifact Registry repo (idempotent)
echo "==> Ensuring Artifact Registry repository exists..."
gcloud artifacts repositories create "${REPO}" \
    --repository-format=docker \
    --location="${REGION}" \
    --project="${PROJECT}" \
    --quiet 2>/dev/null || true

# 2. Build and push image via Cloud Build
echo "==> Building container image with Cloud Build..."
gcloud builds submit \
    --tag "${IMAGE}" \
    --project "${PROJECT}" \
    .

# 3. Build env-var and secret lists
ENV_VARS="GCP_PROJECT=${PROJECT},GCP_LOCATION=${REGION}"
SET_SECRETS=""

if [[ -n "${GITLAB_TOKEN:-}" ]]; then
    echo "==> Storing GITLAB_TOKEN in Secret Manager..."
    echo -n "${GITLAB_TOKEN}" | gcloud secrets create GITLAB_TOKEN \
        --data-file=- --project="${PROJECT}" 2>/dev/null || \
    echo -n "${GITLAB_TOKEN}" | gcloud secrets versions add GITLAB_TOKEN \
        --data-file=- --project="${PROJECT}"
    SET_SECRETS="GITLAB_TOKEN=GITLAB_TOKEN:latest"
fi

if [[ -n "${GEMINI_API_KEY:-}" ]]; then
    echo "==> Storing GEMINI_API_KEY in Secret Manager..."
    echo -n "${GEMINI_API_KEY}" | gcloud secrets create GEMINI_API_KEY \
        --data-file=- --project="${PROJECT}" 2>/dev/null || \
    echo -n "${GEMINI_API_KEY}" | gcloud secrets versions add GEMINI_API_KEY \
        --data-file=- --project="${PROJECT}"
    if [[ -n "${SET_SECRETS}" ]]; then
        SET_SECRETS="${SET_SECRETS},GEMINI_API_KEY=GEMINI_API_KEY:latest"
    else
        SET_SECRETS="GEMINI_API_KEY=GEMINI_API_KEY:latest"
    fi
fi

if [[ -n "${WEBHOOK_SECRET:-}" ]]; then
    echo "==> Storing WEBHOOK_SECRET in Secret Manager..."
    echo -n "${WEBHOOK_SECRET}" | gcloud secrets create WEBHOOK_SECRET \
        --data-file=- --project="${PROJECT}" 2>/dev/null || \
    echo -n "${WEBHOOK_SECRET}" | gcloud secrets versions add WEBHOOK_SECRET \
        --data-file=- --project="${PROJECT}"
    if [[ -n "${SET_SECRETS}" ]]; then
        SET_SECRETS="${SET_SECRETS},WEBHOOK_SECRET=WEBHOOK_SECRET:latest"
    else
        SET_SECRETS="WEBHOOK_SECRET=WEBHOOK_SECRET:latest"
    fi
fi

# Use Vertex AI if no GEMINI_API_KEY provided
if [[ -z "${GEMINI_API_KEY:-}" ]]; then
    ENV_VARS="${ENV_VARS},VERTEX_FLAG=--vertex --gcp-project ${PROJECT}"
fi

# 4. Deploy to Cloud Run
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
    --set-env-vars "${ENV_VARS}"
)

if [[ -n "${SET_SECRETS}" ]]; then
    DEPLOY_CMD+=(--set-secrets "${SET_SECRETS}")
fi

"${DEPLOY_CMD[@]}"

# 5. Print the URL
URL=$(gcloud run services describe "${SERVICE}" \
    --platform managed \
    --region "${REGION}" \
    --project "${PROJECT}" \
    --format "value(status.url)")

echo ""
echo "======================================================"
echo "  PipelineGuard deployed!"
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
