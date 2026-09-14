#!/usr/bin/env bats
load test_helper

setup() {
  setup_common
  TMPREPO="$(mktemp -d)"
  export SECRETS_DIR="$TMPREPO/secrets"
}

teardown() { rm -rf "$TMPREPO"; }

@test "generates all five secrets for a tenant" {
  run "$REPO_ROOT/scripts/secrets-generate.sh" acme
  [ "$status" -eq 0 ]
  for s in postgres_password odoo_admin_passwd pgbouncer_password restic_password canary_password; do
    [ -f "$SECRETS_DIR/acme/$s" ]
  done
}

@test "secrets are mode 0600" {
  "$REPO_ROOT/scripts/secrets-generate.sh" acme
  perms="$(stat -f '%Lp' "$SECRETS_DIR/acme/postgres_password" 2>/dev/null || stat -c '%a' "$SECRETS_DIR/acme/postgres_password")"
  [ "$perms" = "600" ]
}

@test "secrets are at least 32 characters" {
  "$REPO_ROOT/scripts/secrets-generate.sh" acme
  len="$(wc -c < "$SECRETS_DIR/acme/postgres_password" | tr -d ' ')"
  [ "$len" -ge 32 ]
}

@test "rerunning does not overwrite an existing secret" {
  "$REPO_ROOT/scripts/secrets-generate.sh" acme
  before="$(cat "$SECRETS_DIR/acme/postgres_password")"
  "$REPO_ROOT/scripts/secrets-generate.sh" acme
  after="$(cat "$SECRETS_DIR/acme/postgres_password")"
  [ "$before" = "$after" ]
}

@test "secrets contain no trailing newline" {
  "$REPO_ROOT/scripts/secrets-generate.sh" acme
  last="$(tail -c 1 "$SECRETS_DIR/acme/postgres_password" | xxd -p)"
  [ "$last" != "0a" ]
}
