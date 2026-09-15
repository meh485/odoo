#!/usr/bin/env bats
# Shell-level tests for the restore drill. The cluster, psql and the metrics
# endpoint are all mocked, so these run offline and assert on the drill's
# decisions: when it fails, what it reports, and what it always cleans up.
load test_helper

setup() {
  setup_common
  TMP="$(mktemp -d)"
  mkdir -p "$TMP/bin"
  export PATH="$TMP/bin:$PATH"
  export KUBECTL_LOG="$TMP/kubectl.log"
  export KUBECTL_APPLIED="$TMP/applied.yaml"
  export CURL_CAPTURE="$TMP/metrics.txt"
  : > "$KUBECTL_LOG"; : > "$CURL_CAPTURE"; : > "$KUBECTL_APPLIED"

  export TENANT=acme
  export SCRATCH_CLUSTER=acme-restore-scratch
  export SOURCE_CLUSTER=acme-db
  export DB_NAME=acme
  export BACKUP_DESTINATION_PATH="s3://odoo-backups/acme"
  export BACKUP_ENDPOINT_URL="http://minio.storage.svc.cluster.local:9000"
  export BACKUP_CREDENTIALS_SECRET="acme-backup-credentials"
  export PUSHGATEWAY_URL="http://pushgateway.monitoring.svc.cluster.local:9091"
  export MAX_WAIT_SECONDS=5
  export PGPASSFILE="$TMP/.pgpass"

  export PSQL_RES_USERS=5
  export PSQL_TRANSITIONAL=0
  export KUBECTL_WAIT_RC=0

  cat > "$TMP/bin/kubectl" <<'MOCK'
#!/usr/bin/env bash
echo "kubectl $*" >> "$KUBECTL_LOG"
case "$1" in
  apply) cat > "$KUBECTL_APPLIED"; exit 0 ;;
  wait)  exit "${KUBECTL_WAIT_RC:-0}" ;;
  get)   [ "$2" = "secret" ] && printf 'cGFzc3dvcmQ='; exit 0 ;;
  delete) exit 0 ;;
  *) exit 0 ;;
esac
MOCK

  cat > "$TMP/bin/psql" <<'MOCK'
#!/usr/bin/env bash
query="${*: -1}"
case "$query" in
  *res_users*)       printf '%s' "${PSQL_RES_USERS:-5}" ;;
  *ir_module_module*) printf '%s' "${PSQL_TRANSITIONAL:-0}" ;;
  *) printf '0' ;;
esac
MOCK

  cat > "$TMP/bin/curl" <<'MOCK'
#!/usr/bin/env bash
cat >> "$CURL_CAPTURE"
MOCK

  chmod +x "$TMP/bin/"*
}

teardown() { rm -rf "$TMP"; }

drill() { "$REPO_ROOT/scripts/restore-drill.sh"; }

@test "reports success when the restored data passes every assertion" {
  run drill
  [ "$status" -eq 0 ]
  grep -q 'odoo_restore_drill_success{tenant="acme"} 1' "$CURL_CAPTURE"
}

@test "reports the run duration" {
  run drill
  grep -q 'odoo_restore_drill_duration_seconds' "$CURL_CAPTURE"
}

@test "reports failure when the restored database has no users" {
  export PSQL_RES_USERS=0
  run drill
  [ "$status" -ne 0 ]
  grep -q 'odoo_restore_drill_success{tenant="acme"} 0' "$CURL_CAPTURE"
}

@test "reports failure when modules are left transitional" {
  export PSQL_TRANSITIONAL=3
  run drill
  [ "$status" -ne 0 ]
  grep -q 'odoo_restore_drill_success{tenant="acme"} 0' "$CURL_CAPTURE"
}

@test "reports failure when the restored cluster never becomes ready" {
  export KUBECTL_WAIT_RC=1
  run drill
  [ "$status" -ne 0 ]
  grep -q 'odoo_restore_drill_success{tenant="acme"} 0' "$CURL_CAPTURE"
}

@test "always writes a run timestamp, including on failure" {
  export PSQL_RES_USERS=0
  run drill
  grep -q 'odoo_restore_drill_last_run_timestamp_seconds' "$CURL_CAPTURE"
}

@test "always deletes the scratch cluster, including on failure" {
  export PSQL_RES_USERS=0
  run drill
  grep -q "kubectl delete cluster acme-restore-scratch" "$KUBECTL_LOG"
}

@test "always deletes the scratch cluster on success" {
  run drill
  grep -q "kubectl delete cluster acme-restore-scratch" "$KUBECTL_LOG"
}

@test "recovers the scratch cluster from the tenant's object store" {
  run drill
  grep -q 's3://odoo-backups/acme' "$KUBECTL_APPLIED"
  grep -q 'bootstrap:' "$KUBECTL_APPLIED"
  grep -q 'recovery:' "$KUBECTL_APPLIED"
  grep -q 'acme-backup-credentials' "$KUBECTL_APPLIED"
}

@test "names the source cluster so barman finds the backup" {
  # Barman files backups under the source cluster's name; omitting this makes
  # the scratch cluster search for its own name and find nothing.
  run drill
  grep -q 'serverName: acme-db' "$KUBECTL_APPLIED"
}

@test "the scratch cluster is a throwaway single instance" {
  run drill
  grep -q 'instances: 1' "$KUBECTL_APPLIED"
}

@test "never prints a database password" {
  run drill
  [[ "$output" != *"password"* ]]
}
