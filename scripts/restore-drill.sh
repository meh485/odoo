#!/usr/bin/env bash
# Restore drill: prove the latest backup restores into a throwaway
# CloudNativePG Cluster and still holds usable data, then remove it.
#
# CloudNativePG makes backups declarative, not verified. This is the one piece
# of logic no operator provides. Its result is pushed to a Pushgateway so that
# a drill which fails -- or never runs at all -- is visible, because a backup
# nobody has restored is not a backup.
set -euo pipefail

for required in TENANT SCRATCH_CLUSTER SOURCE_CLUSTER DB_NAME BACKUP_DESTINATION_PATH \
                BACKUP_ENDPOINT_URL BACKUP_CREDENTIALS_SECRET PUSHGATEWAY_URL; do
  : "${!required:?missing required environment variable ${required}}"
done

MAX_WAIT_SECONDS="${MAX_WAIT_SECONDS:-900}"
SCRATCH_APP_SECRET="${SCRATCH_CLUSTER}-app"
SCRATCH_HOST="${SCRATCH_CLUSTER}-rw.${TENANT}.svc.cluster.local"
STARTED_AT="$(date +%s)"
PUSH_URL="${PUSHGATEWAY_URL%/}/metrics/job/odoo_restore_drill/tenant/${TENANT}"
RESULT=0

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*"; }

push_metrics() {
  local success="$1" duration="$2"
  {
    printf '# TYPE odoo_restore_drill_success gauge\n'
    printf 'odoo_restore_drill_success{tenant="%s"} %s\n' "$TENANT" "$success"
    printf '# TYPE odoo_restore_drill_duration_seconds gauge\n'
    printf 'odoo_restore_drill_duration_seconds{tenant="%s"} %s\n' "$TENANT" "$duration"
    printf '# TYPE odoo_restore_drill_last_run_timestamp_seconds gauge\n'
    printf 'odoo_restore_drill_last_run_timestamp_seconds{tenant="%s"} %s\n' "$TENANT" "$(date +%s)"
  } | curl -sS --max-time 10 --data-binary @- "$PUSH_URL" >/dev/null \
    || log "WARN: could not push metrics to the Pushgateway"
}

# Runs on every exit, success or failure: reports the outcome, then removes the
# scratch cluster so a failed drill cannot leak quota or disk.
cleanup() {
  local rc=$?
  trap - EXIT
  local duration=$(( $(date +%s) - STARTED_AT ))
  if [ "$rc" -ne 0 ]; then
    RESULT=0
  fi
  push_metrics "$RESULT" "$duration"
  log "deleting scratch cluster ${SCRATCH_CLUSTER}"
  kubectl delete cluster "$SCRATCH_CLUSTER" -n "$TENANT" --ignore-not-found --wait=false >/dev/null 2>&1 \
    || log "WARN: could not delete scratch cluster ${SCRATCH_CLUSTER}"
  exit "$rc"
}
trap cleanup EXIT

log "creating scratch cluster ${SCRATCH_CLUSTER} from ${BACKUP_DESTINATION_PATH}"
kubectl apply -f - <<EOF
apiVersion: postgresql.cnpg.io/v1
kind: Cluster
metadata:
  name: ${SCRATCH_CLUSTER}
  namespace: ${TENANT}
  labels:
    app.kubernetes.io/part-of: restore-drill
spec:
  instances: 1
  storage:
    size: 5Gi
  bootstrap:
    recovery:
      source: ${SCRATCH_CLUSTER}-backup
      database: ${DB_NAME}
      owner: odoo
  externalClusters:
    - name: ${SCRATCH_CLUSTER}-backup
      barmanObjectStore:
        destinationPath: ${BACKUP_DESTINATION_PATH}
        endpointURL: ${BACKUP_ENDPOINT_URL}
        # Barman files backups under the source cluster's name; without this
        # the scratch cluster looks for its own name and finds nothing.
        serverName: ${SOURCE_CLUSTER}
        s3Credentials:
          accessKeyId:
            name: ${BACKUP_CREDENTIALS_SECRET}
            key: ACCESS_KEY_ID
          secretAccessKey:
            name: ${BACKUP_CREDENTIALS_SECRET}
            key: ACCESS_SECRET_KEY
        wal:
          compression: gzip
        data:
          compression: gzip
EOF

log "waiting up to ${MAX_WAIT_SECONDS}s for the restored cluster to become ready"
if ! kubectl wait --for=condition=Ready "cluster/${SCRATCH_CLUSTER}" -n "$TENANT" \
       --timeout="${MAX_WAIT_SECONDS}s" >/dev/null; then
  log "FAIL: the scratch cluster did not become ready"
  exit 1
fi

# The credential is read into a 0600 pgpass file; it never reaches an argument,
# an environment variable or the log.
log "reading the scratch cluster credential"
export PGPASSFILE="${PGPASSFILE:-${TMPDIR:-/tmp}/restore-drill.pgpass}"
umask 077
credential=""
attempt=0
while [ -z "$credential" ]; do
  credential="$(kubectl get secret "$SCRATCH_APP_SECRET" -n "$TENANT" \
    -o go-template='{{.data.password | base64decode}}' 2>/dev/null || true)"
  if [ -z "$credential" ]; then
    attempt=$((attempt + 1))
    [ "$attempt" -ge 30 ] && { log "FAIL: scratch cluster credential never appeared"; exit 1; }
    sleep 5
  fi
done
printf '%s:5432:%s:odoo:%s\n' "$SCRATCH_HOST" "$DB_NAME" "$credential" > "$PGPASSFILE"
chmod 600 "$PGPASSFILE"

log "asserting the restored database holds users"
users="$(psql -h "$SCRATCH_HOST" -U odoo -d "$DB_NAME" -tA -c 'SELECT count(*) FROM res_users;')"
if ! [[ "$users" =~ ^[0-9]+$ ]] || [ "$users" -lt 1 ]; then
  log "FAIL: restored res_users count is '${users}'"
  exit 1
fi

log "asserting no module was left mid-upgrade"
# `uninstallable` is a stable state (a module whose dependencies are absent),
# not a transitional one; only these three mean an upgrade stopped halfway.
transitional="$(psql -h "$SCRATCH_HOST" -U odoo -d "$DB_NAME" -tA \
  -c "SELECT count(*) FROM ir_module_module WHERE state IN ('to install','to upgrade','to remove');")"
if ! [[ "$transitional" =~ ^[0-9]+$ ]] || [ "$transitional" -ne 0 ]; then
  log "FAIL: ${transitional} modules are in a transitional state"
  exit 1
fi

RESULT=1
log "PASS: restored ${users} users and 0 transitional modules"
