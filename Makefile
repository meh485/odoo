SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TENANT ?=
CHART := charts/odoo-tenant
CLUSTER := odoo

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: cluster
cluster: ## Create the local kind cluster
	@kind create cluster --config cluster/kind.yaml --image kindest/node:v1.34.0 --wait 5m

.PHONY: platform
platform: ## Install operators and platform-wide resources
	@scripts/platform-install.sh

# No --wait on the upgrade: Helm can deadlock waiting on the post-install
# hooks on a local cluster and leave the release stuck in pending-upgrade.
# Watch the release with `helm status` and `kubectl get pods` instead.
.PHONY: seed
seed: ## Seed a tenant's credentials into the store External Secrets reads: make seed TENANT=acme
	@test -n "$(TENANT)" || { echo "TENANT is required, e.g. make seed TENANT=acme"; exit 1; }
	@scripts/seed-tenant-credentials.sh "$(TENANT)"

.PHONY: lint
lint: ## Lint the chart
	@helm lint $(CHART) --set tenant.name=acme --set tenant.hostname=acme.odoo.local

.PHONY: test
test: ## Run chart unit tests and shell tests
	@python3 -m pytest tests/ -q
	@bats tests/

.PHONY: e2e
e2e: ## Run the integration tests against the live cluster
	@python3 -m pytest tests/integration -m integration -q
