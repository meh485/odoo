#!/usr/bin/env bats
load test_helper

setup() { setup_common; }

@test "make help lists the tenant target" {
  run make -C "$REPO_ROOT" help
  [ "$status" -eq 0 ]
  [[ "$output" == *"tenant"* ]]
}

@test "require_tenant rejects an invalid tenant name" {
  source "$REPO_ROOT/scripts/lib/common.sh"
  run require_tenant "Bad_Name"
  [ "$status" -ne 0 ]
  [[ "$output" == *"invalid tenant"* ]]
}

@test "require_tenant accepts a valid tenant name" {
  source "$REPO_ROOT/scripts/lib/common.sh"
  run require_tenant "acme"
  [ "$status" -eq 0 ]
}

@test "tenant_project builds the compose project name" {
  source "$REPO_ROOT/scripts/lib/common.sh"
  run tenant_project "acme"
  [ "$output" = "odoo-acme" ]
}
