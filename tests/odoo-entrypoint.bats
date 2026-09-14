#!/usr/bin/env bats
load test_helper

setup() {
  setup_common
  TMP="$(mktemp -d)"
  export SECRETS="$TMP/run-secrets"
  mkdir -p "$SECRETS"
  echo -n "adminpw" > "$SECRETS/odoo_admin_passwd"
  echo -n "dbpw" > "$SECRETS/pgbouncer_password"
  export ODOO_CONF_OUT="$TMP/odoo.conf"
  export SECRETS_PATH="$SECRETS"
  export DB_HOST=pgbouncer DB_PORT=6432 DB_USER=odoo DB_NAME=acme
  export ODOO_WORKERS=3 DBFILTER='^acme$'
  export RENDER_ONLY=1
}

teardown() { rm -rf "$TMP"; }

@test "renders admin_passwd from the secret file" {
  run "$REPO_ROOT/images/odoo/entrypoint.sh"
  [ "$status" -eq 0 ]
  grep -q '^admin_passwd = adminpw$' "$ODOO_CONF_OUT"
}

@test "renders db_password from the secret file" {
  "$REPO_ROOT/images/odoo/entrypoint.sh"
  grep -q '^db_password = dbpw$' "$ODOO_CONF_OUT"
}

@test "disables the database manager" {
  "$REPO_ROOT/images/odoo/entrypoint.sh"
  grep -q '^list_db = False$' "$ODOO_CONF_OUT"
}

@test "enables proxy mode" {
  "$REPO_ROOT/images/odoo/entrypoint.sh"
  grep -q '^proxy_mode = True$' "$ODOO_CONF_OUT"
}

@test "pins the dbfilter" {
  "$REPO_ROOT/images/odoo/entrypoint.sh"
  grep -q '^dbfilter = \^acme\$$' "$ODOO_CONF_OUT"
}

@test "rendered config is not world readable" {
  "$REPO_ROOT/images/odoo/entrypoint.sh"
  perms="$(stat -f '%Lp' "$ODOO_CONF_OUT" 2>/dev/null || stat -c '%a' "$ODOO_CONF_OUT")"
  [ "$perms" = "600" ]
}

@test "fails fast when a secret file is missing" {
  rm "$SECRETS/odoo_admin_passwd"
  run "$REPO_ROOT/images/odoo/entrypoint.sh"
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing secret"* ]]
}

@test "never writes the password to the environment log line" {
  run "$REPO_ROOT/images/odoo/entrypoint.sh"
  [[ "$output" != *"dbpw"* ]]
}
