#!/usr/bin/env bash
# Render odoo.conf from a config template plus mounted secret files, then exec Odoo.
#
# Odoo has no native *_FILE support. Upstream's entrypoint compensates by
# passing the database password as a command-line argument, where it is visible
# in the container's process list. Merging it into a 0600 config file instead
# keeps it out of the process list, out of the pod environment, and out of
# `kubectl describe pod` output. Upstream then skips its own argument injection
# because the value is already present in the config file.
set -euo pipefail

SECRETS_PATH="${SECRETS_PATH:-/etc/odoo-secrets}"
ODOO_CONF_TEMPLATE="${ODOO_CONF_TEMPLATE:-/etc/odoo/odoo.conf.template}"
ODOO_CONF_OUT="${ODOO_CONF_OUT:-/etc/odoo-rendered/odoo.conf}"

read_secret() {
  local path="${SECRETS_PATH}/$1"
  [[ -s "$path" ]] || { echo "missing secret: ${path}" >&2; exit 1; }
  tr -d '\n' < "$path"
}

[[ -s "$ODOO_CONF_TEMPLATE" ]] || {
  echo "missing config template: ${ODOO_CONF_TEMPLATE}" >&2
  exit 1
}

DB_PASSWORD="$(read_secret db_password)"
ADMIN_PASSWD="$(read_secret admin_passwd)"

mkdir -p "$(dirname "$ODOO_CONF_OUT")"
umask 077

# The template carries everything that is not a secret. The two credentials are
# appended here so neither ever appears in the ConfigMap.
cat "$ODOO_CONF_TEMPLATE" > "$ODOO_CONF_OUT"
cat >> "$ODOO_CONF_OUT" <<EOF
db_password = ${DB_PASSWORD}
admin_passwd = ${ADMIN_PASSWD}
workers = ${ODOO_WORKERS:-2}
max_cron_threads = ${ODOO_MAX_CRON_THREADS:-0}
limit_time_cpu = ${ODOO_LIMIT_TIME_CPU:-600}
limit_time_real = ${ODOO_LIMIT_TIME_REAL:-1200}
EOF

chmod 600 "$ODOO_CONF_OUT"
echo "rendered ${ODOO_CONF_OUT} (workers=${ODOO_WORKERS:-2} cron_threads=${ODOO_MAX_CRON_THREADS:-0})"

[[ "${RENDER_ONLY:-0}" == "1" ]] && exit 0

exec odoo --config="$ODOO_CONF_OUT" "$@"
