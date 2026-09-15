#!/usr/bin/env bats
load test_helper

setup() {
  setup_common
  TMP="$(mktemp -d)"
  export SECRETS_PATH="$TMP/secrets"; mkdir -p "$SECRETS_PATH"
  echo -n "dbpw" > "$SECRETS_PATH/db_password"
  echo -n "adminpw" > "$SECRETS_PATH/admin_passwd"
  export ODOO_CONF_TEMPLATE="$TMP/odoo.conf.template"
  cat > "$ODOO_CONF_TEMPLATE" <<EOF
[options]
db_host = acme-pooler-rw
dbfilter = ^acme\$
list_db = False
proxy_mode = True
EOF
  export ODOO_CONF_OUT="$TMP/odoo.conf"
  export ODOO_WORKERS=3
  export RENDER_ONLY=1
}

teardown() { rm -rf "$TMP"; }

render() { "$REPO_ROOT/images/odoo/entrypoint.sh"; }

@test "merges the database password from the secret file" {
  run render
  [ "$status" -eq 0 ]
  grep -q '^db_password = dbpw$' "$ODOO_CONF_OUT"
}

@test "merges the admin password from the secret file" {
  render
  grep -q '^admin_passwd = adminpw$' "$ODOO_CONF_OUT"
}

@test "preserves the non-secret settings from the template" {
  render
  grep -q '^list_db = False$' "$ODOO_CONF_OUT"
  grep -q '^proxy_mode = True$' "$ODOO_CONF_OUT"
  grep -q '^dbfilter = \^acme\$$' "$ODOO_CONF_OUT"
}

@test "applies the worker count from the environment" {
  render
  grep -q '^workers = 3$' "$ODOO_CONF_OUT"
}

@test "rendered config is not world readable" {
  render
  perms="$(stat -f '%Lp' "$ODOO_CONF_OUT" 2>/dev/null || stat -c '%a' "$ODOO_CONF_OUT")"
  [ "$perms" = "600" ]
}

@test "fails fast when the database secret is missing" {
  rm "$SECRETS_PATH/db_password"
  run render
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing secret"* ]]
}

@test "fails fast when the admin secret is missing" {
  rm "$SECRETS_PATH/admin_passwd"
  run render
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing secret"* ]]
}

@test "fails fast when the config template is missing" {
  rm "$ODOO_CONF_TEMPLATE"
  run render
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing config template"* ]]
}

@test "never echoes a password" {
  run render
  [[ "$output" != *"dbpw"* ]]
  [[ "$output" != *"adminpw"* ]]
}
