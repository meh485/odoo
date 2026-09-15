SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TENANT ?=

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: tenant
tenant: ## Provision a tenant: make tenant TENANT=acme
	@scripts/tenant-create.sh "$(TENANT)"

.PHONY: test
test: ## Run the bats test suite
	@bats tests/

.PHONY: secrets
secrets: ## Generate secrets for a tenant: make secrets TENANT=acme
	@scripts/secrets-generate.sh "$(TENANT)"
