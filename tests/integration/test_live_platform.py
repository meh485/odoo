"""End-to-end assertions against the running platform.

Each test is a question an operator would ask before trusting the cluster:
is anything down, can users log in, is the data protected, will we be told
when it breaks, and can one tenant reach another tenant's database.
"""
from __future__ import annotations

import pytest

from .conftest import (
    PROMETHEUS_PROXY,
    kubectl_json,
    kubectl_ok,
    raw_json,
)

pytestmark = pytest.mark.integration


def _scalar(query, expression: str) -> float | None:
    result = query(expression)
    return float(result[0]["value"][1]) if result else None


def test_every_scrape_target_is_up(query, tenants):
    for tenant in tenants:
        down = query(f'up{{namespace="{tenant}"}} == 0')
        assert not down, (
            f"{tenant} has down targets: {[r['metric'] for r in down]}"
        )
        assert _scalar(query, f'count(up{{namespace="{tenant}"}})') > 0, (
            f"{tenant} exposes no scrape targets at all"
        )


def test_canary_login_succeeds(query, tenants):
    for tenant in tenants:
        value = _scalar(query, f'odoo_canary_success{{tenant="{tenant}"}}')
        assert value == 1, f"{tenant} canary reports success={value}"


def test_base_backup_is_recent(query, tenants):
    for tenant in tenants:
        age_hours = _scalar(
            query,
            "(time() - cnpg_collector_last_available_backup_timestamp"
            f'{{namespace="{tenant}"}}) / 3600',
        )
        assert age_hours is not None, f"{tenant} exposes no backup timestamp"
        assert age_hours < 26, f"{tenant} last base backup was {age_hours:.1f}h ago"


def test_restore_drill_is_recorded(query, tenants):
    for tenant in tenants:
        value = _scalar(query, f'odoo_restore_drill_success{{tenant="{tenant}"}}')
        assert value == 1, f"{tenant} restore drill reports success={value}"


def test_expected_alert_rules_are_loaded():
    rules = raw_json(f"{PROMETHEUS_PROXY}/api/v1/rules")
    loaded = {
        rule["name"]
        for group in rules["data"]["groups"]
        for rule in group["rules"]
    }
    expected = {
        "OdooCanaryFailed",
        "OdooCanaryStale",
        "OdooBackupStale",
        "OdooRestoreDrillFailed",
        "OdooCronStalled",
        "OdooLockContention",
    }
    assert expected <= loaded, f"missing rules: {sorted(expected - loaded)}"


def test_grafana_has_a_default_prometheus_datasource():
    config_map = kubectl_json(
        "get", "configmap", "kube-prometheus-stack-grafana-datasource",
        "-n", "monitoring",
    )
    blob = "\n".join(config_map.get("data", {}).values())
    assert "uid: prometheus" in blob, "Grafana has no datasource with uid prometheus"
    assert "isDefault: true" in blob, "no Grafana datasource is marked default"


def test_tenant_cannot_reach_the_monitoring_namespace(tenants):
    """A tenant pod cannot open a connection into the monitoring namespace."""
    if not tenants:
        pytest.skip("no tenant is installed")
    tenant = tenants[0]

    assert _can_connect(tenant, f"{tenant}-pooler", 5432), (
        f"control failed: {tenant}'s web pod cannot reach its own pooler, so "
        "the negative result below would prove nothing"
    )
    assert not _can_connect(
        tenant, "kube-prometheus-stack-prometheus.monitoring.svc.cluster.local", 9090
    ), f"{tenant} reached Prometheus; the monitoring namespace is not isolated"


def test_one_tenant_cannot_reach_anothers_database(tenants):
    """A tenant pod cannot reach another tenant's pooler."""
    if len(tenants) < 2:
        pytest.skip("needs at least two installed tenants")
    source, target = tenants[0], tenants[1]
    assert not _can_connect(
        source, f"{target}-pooler.{target}.svc.cluster.local", 5432
    ), f"{source} reached {target}'s database; tenant isolation is broken"


def _can_connect(tenant: str, host: str, port: int) -> bool:
    """Return True when the tenant's own web pod can open a TCP connection.

    This runs inside the real web pod rather than in a probe pod: the web pod
    already carries the labels and DNS access the network policies were
    written for, so a failure is the policy and not a label that was missed.
    """
    script = f"import socket; socket.create_connection(('{host}', {port}), 5).close()"
    return kubectl_ok(
        "exec", f"deploy/{tenant}-web", "-n", tenant,
        "--", "python3", "-c", script, timeout=30,
    ) is not None