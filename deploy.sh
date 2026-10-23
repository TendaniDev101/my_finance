#!/usr/bin/env bash
# Deploys the JSE Portfolio Builder backend to Cloud Run.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated (`gcloud auth login`)
#   - A GCP project with billing enabled (required even to stay within the
#     free tier) and the Cloud Run + Cloud Build APIs enabled:
#       gcloud services enable run.googleapis.com cloudbuild.googleapis.com
#
# Usage:
#   GCP_PROJECT_ID=your-project-id ./deploy.sh
#
# After the frontend is live on Cloudflare Pages, re-run with:
#   GCP_PROJECT_ID=your-project-id ALLOWED_ORIGINS=https://your-app.pages.dev ./deploy.sh
set -euo pipefail

PROJECT_ID="${GCP_PROJECT_ID:?Set GCP_PROJECT_ID, e.g. GCP_PROJECT_ID=my-project ./deploy.sh}"
REGION="${GCP_REGION:-us-central1}"
SERVICE_NAME="${SERVICE_NAME:-jse-portfolio-builder}"
ALLOWED_ORIGINS="${ALLOWED_ORIGINS:-*}"

cd "$(dirname "$0")"

gcloud run deploy "$SERVICE_NAME" \
  --source . \
  --project "$PROJECT_ID" \
  --region "$REGION" \
  --allow-unauthenticated \
  --min-instances=0 \
  --max-instances=4 \
  --memory=512Mi \
  --cpu=1 \
  --cpu-boost \
  --concurrency=4 \
  --timeout=120 \
  --set-env-vars="ALLOWED_ORIGINS=${ALLOWED_ORIGINS}"

echo
echo "Deployed. Settings worth knowing:"
echo "  --min-instances=0   -> scales to zero, \$0 while idle (the whole point)"
echo "  --cpu-boost         -> extra CPU during cold start only, to offset the"
echo "                         numpy/pandas/scipy import cost - free, no downside"
echo "  --memory=512Mi       -> bump to 1Gi if you see OOM errors in the logs"
echo "  ALLOWED_ORIGINS=${ALLOWED_ORIGINS}"
if [ "$ALLOWED_ORIGINS" = "*" ]; then
  echo "    (wildcard - fine for now since there's no auth/cookies, but once"
  echo "     the Cloudflare Pages URL is known, re-run with ALLOWED_ORIGINS set"
  echo "     to that exact URL to stop any other site from calling this API)"
fi
