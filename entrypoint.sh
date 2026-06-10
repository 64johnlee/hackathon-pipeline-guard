#!/bin/sh
# Container entrypoint. On GCP (Cloud Run) the runtime service account provides
# Application Default Credentials automatically. On non-GCP hosts (e.g. a
# Hugging Face Space) there is no metadata server, so allow a service-account
# key to be injected as the GOOGLE_CREDENTIALS_JSON env var (or HF "secret").
# When present, materialise it to a file and point ADC at it.
if [ -n "${GOOGLE_CREDENTIALS_JSON:-}" ]; then
  printf '%s' "${GOOGLE_CREDENTIALS_JSON}" > /tmp/gcp-sa.json
  export GOOGLE_APPLICATION_CREDENTIALS=/tmp/gcp-sa.json
fi

exec pipelineguard serve \
  --host 0.0.0.0 \
  --port "${PORT}" \
  ${VERTEX_FLAG}
