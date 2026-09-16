#!/usr/bin/env bash
# Create a tenant's admin password Secret if it does not already exist.
#
# The chart only references this Secret; it never creates it. A password
# generated during a helm render changes on every render, which Argo CD would
# see as permanent drift and would sync as a rotated credential.
#
# Creating it here is also what keeps the production path free of chart
# changes: External Secrets Operator writes the same Secret from Vault, and
# neither the templates nor a tenant's values file are touched.
set -euo pipefail

TENANT="${1:?usage: seed-admin-credentials.sh TENANT}"
NAMESPACE="${TENANT}"
SECRET="${TENANT}-odoo-admin"

if ! kubectl get namespace "$NAMESPACE" >/dev/null 2>&1; then
  echo "namespace ${NAMESPACE} does not exist yet; skipping"
  exit 0
fi

if kubectl get secret "$SECRET" -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "${SECRET} already exists; leaving it untouched"
  exit 0
fi

# ADMIN_PASSWD supplies the value instead of generating one, which is how an
# existing tenant keeps its password when it moves to this scheme.
password="${ADMIN_PASSWD:-$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 40)}"

kubectl create secret generic "$SECRET" -n "$NAMESPACE" \
  --from-literal=admin_passwd="$password" >/dev/null
echo "created ${SECRET}"
