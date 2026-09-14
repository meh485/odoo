SHELL := /usr/bin/env bash
.DEFAULT_GOAL := help

TENANT ?=

.PHONY: help
help: ## Show available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  %-18s %s\n", $$1, $$2}'

.PHONY: networks
networks: ## Create the shared edge and monitoring networks
	@docker network inspect odoo_edge >/dev/null 2>&1 || docker network create odoo_edge
	@docker network inspect odoo_monitoring >/dev/null 2>&1 || docker network create odoo_monitoring

.PHONY: tenant
tenant: ## Provision a tenant: make tenant TENANT=acme
	@scripts/tenant-create.sh "$(TENANT)"

.PHONY: test
test: ## Run the bats test suite
	@bats tests/
