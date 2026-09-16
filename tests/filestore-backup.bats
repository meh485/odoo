#!/usr/bin/env bats
# Shell-level tests for the filestore backup. restic is mocked, so these run
# offline and assert on the decisions the script makes: when it initialises,
# what it scopes its retention to, and how it handles the object store key.
load test_helper

setup() {
  setup_common
  TMP="$(mktemp -d)"
  mkdir -p "$TMP/bin" "$TMP/credentials" "$TMP/filestore"
  export PATH="$TMP/bin:$PATH"
  export RESTIC_LOG="$TMP/restic.log"
  : > "$RESTIC_LOG"

  export TENANT=acme
  export RESTIC_REPOSITORY="s3:http://minio:9000/odoo-backups/acme-filestore"
  export RESTIC_PASSWORD_FILE="$TMP/restic_password"
  printf 'repo-password' > "$RESTIC_PASSWORD_FILE"
  export AWS_SHARED_CREDENTIALS_FILE="$TMP/aws/credentials"
  export CREDENTIALS_DIR="$TMP/credentials"
  export FILESTORE_DIR="$TMP/filestore"
  printf 'AKIDEXAMPLE' > "$CREDENTIALS_DIR/ACCESS_KEY_ID"
  printf 'secret-example' > "$CREDENTIALS_DIR/ACCESS_SECRET_KEY"
  export RESTIC_CAT_RC=0

  cat > "$TMP/bin/restic" <<'MOCK'
#!/usr/bin/env bash
echo "restic $*" >> "$RESTIC_LOG"
case "$1" in
  cat) exit "${RESTIC_CAT_RC:-0}" ;;
  init) echo "created restic repository"; exit 0 ;;
  backup|forget) exit 0 ;;
  *) exit 0 ;;
esac
MOCK
  chmod +x "$TMP/bin/restic"
}

teardown() { rm -rf "$TMP"; }

backup() { "$REPO_ROOT/scripts/filestore-backup.sh"; }

@test "initialises a repository that does not exist yet" {
  export RESTIC_CAT_RC=10
  run backup
  [ "$status" -eq 0 ]
  grep -q "restic init" "$RESTIC_LOG"
}

@test "does not re-initialise an existing repository" {
  export RESTIC_CAT_RC=0
  run backup
  [ "$status" -eq 0 ]
  ! grep -q "restic init" "$RESTIC_LOG"
}

@test "backs up with a tenant-scoped tag and hostname" {
  run backup
  grep -Eq "restic backup .*--tag filestore --host acme" "$RESTIC_LOG"
}

@test "never runs an unscoped forget" {
  # An unscoped forget in a shared repository could delete another tenant's
  # snapshots; the tag and hostname must both be present.
  run backup
  line="$(grep 'restic forget' "$RESTIC_LOG")"
  [[ "$line" == *"--tag filestore"* ]]
  [[ "$line" == *"--host acme"* ]]
}

@test "writes the object store key as a 0600 file rather than an environment variable" {
  run backup
  [ -f "$AWS_SHARED_CREDENTIALS_FILE" ]
  grep -q 'aws_access_key_id=AKIDEXAMPLE' "$AWS_SHARED_CREDENTIALS_FILE"
  grep -q 'aws_secret_access_key=secret-example' "$AWS_SHARED_CREDENTIALS_FILE"
  perms="$(file_perms "$AWS_SHARED_CREDENTIALS_FILE")"
  [ "$perms" = "600" ]
}

@test "fails fast when a required variable is missing" {
  unset RESTIC_REPOSITORY
  run backup
  [ "$status" -ne 0 ]
  [[ "$output" == *"missing RESTIC_REPOSITORY"* ]]
}