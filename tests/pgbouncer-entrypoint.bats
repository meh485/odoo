#!/usr/bin/env bats
load test_helper

setup() {
  setup_common
  TMP="$(mktemp -d)"
  export SECRETS_PATH="$TMP/secrets"; mkdir -p "$SECRETS_PATH"
  echo -n "dbpw" > "$SECRETS_PATH/pgbouncer_password"
  export PGB_CONF_DIR="$TMP/conf"
  export DB_HOST=postgres DB_NAME=acme DB_USER=odoo
  export RENDER_ONLY=1
}

teardown() { rm -rf "$TMP"; }

@test "uses session pooling, never transaction pooling" {
  run "$REPO_ROOT/images/pgbouncer/entrypoint.sh"
  [ "$status" -eq 0 ]
  grep -q '^pool_mode = session$' "$PGB_CONF_DIR/pgbouncer.ini"
  ! grep -q 'pool_mode = transaction' "$PGB_CONF_DIR/pgbouncer.ini"
}

@test "writes a scram userlist entry for the odoo user" {
  "$REPO_ROOT/images/pgbouncer/entrypoint.sh"
  grep -q '^"odoo"' "$PGB_CONF_DIR/userlist.txt"
}

@test "userlist is mode 0600" {
  "$REPO_ROOT/images/pgbouncer/entrypoint.sh"
  perms="$(stat -f '%Lp' "$PGB_CONF_DIR/userlist.txt" 2>/dev/null || stat -c '%a' "$PGB_CONF_DIR/userlist.txt")"
  [ "$perms" = "600" ]
}

@test "fails fast without the password secret" {
  rm "$SECRETS_PATH/pgbouncer_password"
  run "$REPO_ROOT/images/pgbouncer/entrypoint.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing secret"* ]]
}
