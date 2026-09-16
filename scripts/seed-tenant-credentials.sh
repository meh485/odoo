#!/usr/bin/env bash
# Create a tenant's generated credentials if they do not already exist.
#
# The chart only references these Secrets; it never creates them. A password
# generated during a helm render changes on every render, so Argo CD would see
# permanent drift, and syncing it would rotate whatever consumes the value --
# for restic, that means making every existing snapshot unreadable.
#
# The backup credential is deliberately not here: seed-backup-credentials.sh
# copies it from the object store's own credential, so there is one source of
# truth for it. In production External Secrets Operator writes all of these
# from Vault, and neither the chart nor a tenant's values file changes.
set -euo pipefail

TENANT="${1:?usage: seed-tenant-credentials.sh TENANT}"
NAMESPACE="${TENANT}"

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "namespace ${NAMESPACE} does not exist yet; skipping"
  exit 0
fi

# seed SECRET KEY [SUPPLIED]
#
# SUPPLIED lets a caller pass an existing value instead of generating one,
# which is how a tenant keeps its credentials when it moves to this scheme.
seed() {
  local secret="$1" key="$2" supplied="${3:-}"

  if kubectl get secret "$secret" -n "$NAMESPACE" >/dev/null 2>&1; then
    echo "${secret} already exists; leaving it untouched"
    return 0
  fi

  local value="$supplied"
  if [ -z "$value" ]; then
    # openssl, not `tr /dev/urandom | head`: under `set -o pipefail` the head
    # exits first and kills tr with SIGPIPE, so the pipeline reports 141 and
    # this script aborts without creating anything.
    value="$(openssl rand -hex 24)"
  fi

  kubectl create secret generic "$secret" -n "$NAMESPACE" \
    --from-literal="$key=$value" >/dev/null
  echo "created ${secret}"
}

seed "${TENANT}-odoo-admin" admin_passwd "${ADMIN_PASSWD:-}"
seed "${TENANT}-canary" canary_password "${CANARY_PASSWORD:-}"
seed "${TENANT}-restic" restic_password "${RESTIC_PASSWORD:-}"
