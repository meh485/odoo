#!/usr/bin/env bash
# Seed a tenant's credentials into the store that External Secrets reads from.
#
# Three are generated and two are copied from the object store's own credential,
# so there is one source of truth for each. This is the stand-in for Vault: with
# a real backend these values are already in it and this script is not used.
#
# It writes one Secret per tenant into the credentials namespace and touches no
# tenant namespace at all. The tenant namespace does not exist when this runs --
# under ArgoCD the chart creates it, along with the ExternalSecrets that
# materialise these values into it.
set -euo pipefail

TENANT="${1:?usage: seed-tenant-credentials.sh TENANT}"
NAMESPACE="${CREDENTIALS_NAMESPACE:-odoo-credentials}"
SECRET="${TENANT}"

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "namespace ${NAMESPACE} does not exist yet; is the platform installed?"
  exit 1
fi

if kubectl get secret "$SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "${NAMESPACE}/${SECRET} already exists; leaving it untouched"
  exit 0
fi

# A tenant whose object store credential does not exist yet has nothing to copy,
# and this must not quietly produce a half-populated Secret.
if ! kubectl get secret minio-credentials -n storage >/dev/null 2>&1; then
  echo "no storage/minio-credentials Secret; cannot seed the object store keys"
  exit 1
fi

# ADMIN_PASSWD and friends let a caller supply an existing value instead of
# generating one, which is how a tenant keeps its credentials when it moves to
# this scheme. To rotate one, delete the Secret and seed it again.
#
# openssl, not `tr /dev/urandom | head`: under `set -o pipefail` the head exits
# first and kills tr with SIGPIPE, so the pipeline reports 141 and this script
# aborts without creating anything.
admin="${ADMIN_PASSWD:-$(openssl rand -hex 24)}"
canary="${CANARY_PASSWORD:-$(openssl rand -hex 24)}"
restic="${RESTIC_PASSWORD:-$(openssl rand -hex 24)}"
access_key_id="$(kubectl get secret minio-credentials -n storage \
  -o go-template='{{.data.ACCESS_KEY_ID | base64decode}}')"
secret_access_key="$(kubectl get secret minio-credentials -n storage \
  -o go-template='{{.data.ACCESS_SECRET_KEY | base64decode}}')"

kubectl create secret generic "$SECRET" -n "$NAMESPACE" \
  --from-literal=admin_passwd="$admin" \
  --from-literal=canary_password="$canary" \
  --from-literal=restic_password="$restic" \
  --from-literal=ACCESS_KEY_ID="$access_key_id" \
  --from-literal=ACCESS_SECRET_KEY="$secret_access_key" >/dev/null
echo "seeded ${NAMESPACE}/${SECRET} with the five credential keys"
