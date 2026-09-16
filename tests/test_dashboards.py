"""The dashboards are provisioned from ConfigMaps, so a malformed JSON body or
a query pinned to one tenant's namespace ships silently: Grafana logs an error
and the panel is simply absent.

These tests cover both, and they run without a cluster.
"""
import json
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_FILES = [
    REPO_ROOT / "platform" / "monitoring" / "dashboards.yaml",
    REPO_ROOT / "platform" / "monitoring" / "dashboards-ops.yaml",
]


def dashboards():
    for path in DASHBOARD_FILES:
        for document in yaml.safe_load_all(path.read_text()):
            if not document:
                continue
            for name, body in (document.get("data") or {}).items():
                yield path.name, name, json.loads(body)


def test_every_dashboard_body_is_valid_json_with_a_uid():
    found = list(dashboards())
    assert found, "no dashboards found to check"
    for name, key, dashboard in found:
        assert dashboard.get("uid"), f"{name}:{key} has no uid"
        assert dashboard.get("panels"), f"{name}:{key} has no panels"


def test_no_dashboard_is_pinned_to_one_tenant():
    for name, key, dashboard in dashboards():
        # Un-escape: a PromQL label matcher inside a JSON string arrives as
        # \"acme\", which a plain '"acme"' search would never match.
        text = json.dumps(dashboard).replace('\\"', '"')
        for tenant in ('"acme"', '"beta"'):
            assert tenant not in text, (
                f"{name}:{key} hardcodes the tenant {tenant}; use $tenant"
            )


def test_a_dashboard_using_the_tenant_variable_declares_it():
    for name, key, dashboard in dashboards():
        if "$tenant" not in json.dumps(dashboard):
            continue
        declared = {
            variable["name"]
            for variable in dashboard.get("templating", {}).get("list", [])
        }
        assert "tenant" in declared, (
            f"{name}:{key} uses $tenant without declaring the variable"
        )
