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
	@kind create cluster --config .local/cluster/kind.yaml --image kindest/node:v1.34.0 --wait 5m

.PHONY: platform
platform: ## Install operators and platform-wide resources
	@scripts/platform-install.sh

.PHONY: tenant
tenant: ## Install or upgrade a tenant: make tenant TENANT=acme
	@helm upgrade --install "$(TENANT)" $(CHART) \
		--namespace "$(TENANT)" --create-namespace \
		--values tenants/$(TENANT).yaml --wait

.PHONY: secrets
secrets: ## Generate secrets for a tenant: make secrets TENANT=acme
	@scripts/secrets-generate.sh "$(TENANT)"

.PHONY: lint
lint: ## Lint the chart
	@helm lint $(CHART) --set tenant.name=acme --set tenant.hostname=acme.odoo.local

.PHONY: test
test: ## Run chart unit tests and shell tests
	@python3 -m pytest tests/ -q
	@bats tests/
