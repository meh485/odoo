"""The chart wires each tenant into Prometheus itself: monitors for the metrics
the rules read, and the rules that make a silent failure loud.
"""
from conftest import by_kind, helm_template, one

DISABLED = {"observability": {"enabled": False}}
ALERTS = {
    "OdooBackupStale",
    "OdooBackupMissing",
    "OdooWalArchivingStalled",
    "OdooRestoreDrillFailed",
    "OdooCanaryFailed",
    "OdooCronStalled",
    "OdooMailQueueStalled",
    "OdooAttachmentDrift",
    "OdooLockContention",
}


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


def test_a_tenant_that_never_backed_up_is_not_called_stale(manifests) -> None:
    # Zero means "no backup yet", and it sits far enough in the past to satisfy
    # the staleness threshold on its own, so the guard is what stops a new
    # tenant from paging before its first scheduled run.
    exprs = {rule["alert"]: rule["expr"] for group in rules(helm_template()) for rule in group["rules"]}
    assert "> 0" in exprs["OdooBackupStale"]
    assert "== 0" in exprs["OdooBackupMissing"]


def test_sql_exporter_is_deployed_and_scraped(manifests) -> None:
    one(manifests, "Deployment", "sql-exporter")
    one(manifests, "Service", "sql-exporter")
    one(manifests, "ServiceMonitor", "sql-exporter")


def test_sql_exporter_takes_its_credential_from_a_file(manifests) -> None:
    pod = one(manifests, "Deployment", "sql-exporter")["spec"]["template"]["spec"]
    for entry in pod["containers"][0].get("env", []):
        assert "secretKeyRef" not in str(entry.get("valueFrom", {}))
    credentials = next(v for v in pod["volumes"] if v["name"] == "db-credentials")
    assert credentials["secret"]["secretName"] == "acme-db-app"
    assert credentials["secret"]["defaultMode"] == 0o400


def test_sql_exporter_queries_the_odoo_domain_tables(manifests) -> None:
    data = one(manifests, "ConfigMap", "sql-exporter")["data"]
    assert "run.sh" in data
    collectors = [key for key in data if key.endswith(".collector.yml")]
    assert len(collectors) == 4, collectors
    joined = " ".join(data.values())
    for table in ("ir_cron", "mail_mail", "ir_attachment", "pg_stat_activity"):
        assert table in joined, f"{table} is not queried"


def test_sql_exporter_may_reach_postgres(manifests) -> None:
    names = {policy["metadata"]["name"] for policy in by_kind(manifests, "NetworkPolicy")}
    assert any("sql-exporter-egress" in name for name in names)