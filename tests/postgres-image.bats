#!/usr/bin/env bats
load test_helper

setup() { setup_common; }

# --pull=never keeps a missing local image failing immediately instead of
# stalling while Docker tries to fetch a tag that does not exist upstream.
run_in_image() {
  docker run --rm --pull=never --entrypoint "$1" odoo-postgres:local "${@:2}"
}

@test "postgres image builds" {
  run docker build -t odoo-postgres:local "$REPO_ROOT/images/postgres"
  [ "$status" -eq 0 ]
}

@test "pgbackrest is installed in the image" {
  run run_in_image pgbackrest version
  [ "$status" -eq 0 ]
  [[ "$output" == *"pgBackRest"* ]]
}

@test "image does not run as root by default" {
  run run_in_image id -u
  [ "$status" -eq 0 ]
  [ "$output" != "0" ]
}

@test "odoo tuning file is present and owned by postgres" {
  run run_in_image stat -c '%U %a' /etc/postgresql/conf.d/10-odoo.conf
  [ "$status" -eq 0 ]
  [[ "$output" == postgres* ]]
}

@test "wal archiving is configured" {
  run run_in_image grep -c 'archive_mode = on' /etc/postgresql/conf.d/10-odoo.conf
  [ "$output" = "1" ]
}

@test "scram authentication is configured" {
  run run_in_image grep -c "password_encryption = 'scram-sha-256'" /etc/postgresql/conf.d/10-odoo.conf
  [ "$output" = "1" ]
}
