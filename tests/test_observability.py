"""The chart wires each tenant into Prometheus itself: monitors for the metrics
the rules read, and the rules that make a silent failure loud.
"""
from conftest import by_kind, helm_template, one

DISABLED = {"observability": {"enabled": False}}
ALERTS = {"OdooBackupStale", "OdooWalArchivingStalled", "OdooRestoreDrillFailed", "OdooCanaryFailed"}


def rules(manifests) -> list[dict]:
    return by_kind(manifests, "PrometheusRule")[0]["spec"]["groups"]


def test_monitors_are_rendered_when_enabled(manifests) -> None:
    assert one(manifests, "ServiceMonitor", "canary")
    assert one(manifests, "PodMonitor", "-db")
    assert one(manifests, "PodMonitor", "pooler")
    assert one(manifests, "PrometheusRule")


def test_nothing_is_rendered_when_observability_is_disabled() -> None:
    manifests = helm_template(DISABLED)
    for kind in ("ServiceMonitor", "PodMonitor", "PrometheusRule"):
        assert not by_kind(manifests, kind), f"{kind} rendered while observability is disabled"


def test_canary_monitor_scrapes_the_metrics_port(manifests) -> None:
    endpoint = one(manifests, "ServiceMonitor", "canary")["spec"]["endpoints"][0]
    assert endpoint["port"] == "metrics"


def test_postgres_monitor_targets_the_cluster(manifests) -> None:
    monitor = one(manifests, "PodMonitor", "-db")
    assert monitor["spec"]["selector"]["matchLabels"]["cnpg.io/cluster"] == "acme-db"
    assert monitor["spec"]["podMetricsEndpoints"][0]["port"] == "metrics"


def test_the_silent_failure_alerts_are_present(manifests) -> None:
    names = {rule["alert"] for group in rules(helm_template()) for rule in group["rules"]}
    assert ALERTS <= names, f"missing alerts: {sorted(ALERTS - names)}"


def test_every_alert_carries_a_severity(manifests) -> None:
    for group in rules(helm_template()):
        for rule in group["rules"]:
            assert rule["labels"]["severity"] in {"warning", "critical"}, rule["alert"]


def test_alerts_are_scoped_to_this_tenant(manifests) -> None:
    # A rule that fired for every tenant would be noise, not a page.
    for group in rules(helm_template()):
        for rule in group["rules"]:
            assert 'tenant="acme"' in rule["expr"] or 'namespace="acme"' in rule["expr"], rule["alert"]


def test_backup_staleness_uses_the_verified_metric(manifests) -> None:
    # The metric name was read off the live instance manager, not assumed.
    exprs = {rule["alert"]: rule["expr"] for group in rules(helm_template()) for rule in group["rules"]}
    assert "cnpg_collector_last_available_backup_timestamp" in exprs["OdooBackupStale"]