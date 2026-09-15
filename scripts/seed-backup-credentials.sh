#!/usr/bin/env bash
# Seed a tenant's backup credential from the object store's root credential.
#
# The chart preserves an existing {tenant}-backup-credentials Secret across
# upgrades, so creating it here is safe and keeps the credential out of git.
set -euo pipefail

TENANT="${1:?usage: seed-backup-credentials.sh TENANT}"
NAMESPACE="${TENANT}"
SECRET="${TENANT}-backup-credentials"

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "namespace ${NAMESPACE} does not exist yet; skipping"
  exit 0
fi

# A tenant created before the object store exists has nothing to be seeded from.
if ! kubectl get secret minio-credentials -n storage >/dev/null 2>&1; then
  echo "no storage/minio-credentials Secret; skipping backup credential seeding"
  exit 0
fi

if kubectl get secret "$SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "${SECRET} already exists; leaving it untouched"
  exit 0
fi

access_key_id="$(kubectl get secret minio-credentials -n storage \
  -o go-template='{{.data.ACCESS_KEY_ID | base64decode}}')"
secret_access_key="$(kubectl get secret minio-credentials -n storage \
  -o go-template='{{.data.ACCESS_SECRET_KEY | base64decode}}')"

kubectl create secret generic "$SECRET" -n "$NAMESPACE" \
  --from-literal=ACCESS_KEY_ID="$access_key_id" \
  --from-literal=ACCESS_SECRET_KEY="$secret_access_key"
echo "seeded ${SECRET} from storage/minio-credentials"