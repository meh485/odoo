#!/usr/bin/env bash
# Generate per-tenant secrets. Idempotent: existing secrets are never replaced,
# because overwriting a live Postgres password locks the tenant out of its data.
set -euo pipefail

source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

TENANT="${1:?usage: secrets-generate.sh <tenant>}"
require_tenant "$TENANT"

SECRETS_DIR="${SECRETS_DIR:-$(dirname "${BASH_SOURCE[0]}")/../secrets}"
TENANT_DIR="${SECRETS_DIR}/${TENANT}"

SECRET_NAMES=(
  postgres_password
  odoo_admin_passwd
  pgbouncer_password
  restic_password
  canary_password
)

mkdir -p "$TENANT_DIR"
chmod 700 "$TENANT_DIR"

for name in "${SECRET_NAMES[@]}"; do
  target="${TENANT_DIR}/${name}"
  if [[ -s "$target" ]]; then
    echo "keep   ${TENANT}/${name} (already present)"
    continue
  fi
  # -base64 then strip characters that need escaping in libpq connection URIs.
  openssl rand -base64 48 | tr -d '\n=+/' | cut -c1-40 | tr -d '\n' > "$target"
  chmod 600 "$target"
  echo "create ${TENANT}/${name}"
done
