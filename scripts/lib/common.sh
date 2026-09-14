#!/usr/bin/env bash
# Shared helpers for tenant lifecycle scripts.
set -euo pipefail

die() {
  echo "error: $*" >&2
  return 1
}

require_tenant() {
  local name="${1:-}"
  if [[ ! "$name" =~ ^[a-z][a-z0-9-]{1,30}$ ]]; then
    die "invalid tenant name '${name}': must match ^[a-z][a-z0-9-]{1,30}$"
    return 1
  fi
}

tenant_project() {
  local name="${1:?tenant required}"
  echo "odoo-${name}"
}
