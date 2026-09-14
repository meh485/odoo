#!/usr/bin/env bash
# Render PgBouncer configuration from mounted secrets.
#
# pool_mode is session, not transaction: Odoo relies on prepared statements and
# session-level state, and transaction pooling breaks them intermittently rather
# than cleanly, producing errors that are very hard to attribute.
set -euo pipefail

SECRETS_PATH="${SECRETS_PATH:-/run/secrets}"
PGB_CONF_DIR="${PGB_CONF_DIR:-/etc/pgbouncer}"

read_secret() {
  local path="${SECRETS_PATH}/$1"
  [[ -s "$path" ]] || { echo "missing secret: ${path}" >&2; exit 1; }
  tr -d '\n' < "$path"
}

DB_PASSWORD="$(read_secret pgbouncer_password)"
DB_USER="${DB_USER:-odoo}"

mkdir -p "$PGB_CONF_DIR"
umask 077

cat > "${PGB_CONF_DIR}/pgbouncer.ini" <<EOF
[databases]
${DB_NAME:-odoo} = host=${DB_HOST:-postgres} port=5432 dbname=${DB_NAME:-odoo}

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = ${PGB_CONF_DIR}/userlist.txt
pool_mode = session
max_client_conn = ${PGB_MAX_CLIENT_CONN:-200}
default_pool_size = ${PGB_DEFAULT_POOL_SIZE:-25}
reserve_pool_size = 5
reserve_pool_timeout = 3
server_lifetime = 3600
server_idle_timeout = 600
ignore_startup_parameters = extra_float_digits
logfile =
pidfile =
admin_users = ${DB_USER}
stats_users = ${DB_USER}
EOF

printf '"%s" "%s"\n' "$DB_USER" "$DB_PASSWORD" > "${PGB_CONF_DIR}/userlist.txt"
chmod 600 "${PGB_CONF_DIR}/userlist.txt" "${PGB_CONF_DIR}/pgbouncer.ini"
echo "rendered pgbouncer configuration (pool_mode=session)"

[[ "${RENDER_ONLY:-0}" == "1" ]] && exit 0

exec pgbouncer "${PGB_CONF_DIR}/pgbouncer.ini"
