#!/usr/bin/env bash
# Render odoo.conf from mounted secret files, then exec Odoo.
#
# Odoo has no native *_FILE support, so the secret-file contract is honoured
# here rather than by passing passwords through the environment, where they
# would be visible to `docker inspect` and to anything reading /proc.
set -euo pipefail

SECRETS_PATH="${SECRETS_PATH:-/run/secrets}"
ODOO_CONF_OUT="${ODOO_CONF_OUT:-/tmp/odoo/odoo.conf}"

read_secret() {
  local name="$1" path="${SECRETS_PATH}/$1"
  [[ -s "$path" ]] || { echo "missing secret: ${path}" >&2; exit 1; }
  tr -d '\n' < "$path"
}

ADMIN_PASSWD="$(read_secret odoo_admin_passwd)"
DB_PASSWORD="$(read_secret pgbouncer_password)"

mkdir -p "$(dirname "$ODOO_CONF_OUT")"
umask 077

cat > "$ODOO_CONF_OUT" <<EOF
[options]
admin_passwd = ${ADMIN_PASSWD}
db_host = ${DB_HOST:-pgbouncer}
db_port = ${DB_PORT:-6432}
db_user = ${DB_USER:-odoo}
db_password = ${DB_PASSWORD}
db_name = ${DB_NAME:-odoo}
dbfilter = ${DBFILTER:-^odoo\$}
list_db = False
proxy_mode = True
workers = ${ODOO_WORKERS:-2}
max_cron_threads = ${ODOO_MAX_CRON_THREADS:-0}
limit_time_cpu = ${ODOO_LIMIT_TIME_CPU:-600}
limit_time_real = ${ODOO_LIMIT_TIME_REAL:-1200}
limit_memory_soft = ${ODOO_LIMIT_MEMORY_SOFT:-2147483648}
limit_memory_hard = ${ODOO_LIMIT_MEMORY_HARD:-2684354560}
data_dir = /var/lib/odoo
logfile = None
log_level = ${ODOO_LOG_LEVEL:-info}
EOF

chmod 600 "$ODOO_CONF_OUT"
echo "rendered ${ODOO_CONF_OUT} (workers=${ODOO_WORKERS:-2} cron_threads=${ODOO_MAX_CRON_THREADS:-0})"

[[ "${RENDER_ONLY:-0}" == "1" ]] && exit 0

exec odoo --config="$ODOO_CONF_OUT" "$@"
