from conftest import helm_template, one


def test_cluster_is_declared(manifests):
    cluster = one(manifests, "Cluster")
    assert cluster["apiVersion"].startswith("postgresql.cnpg.io/")
    assert cluster["spec"]["instances"] >= 1


def test_pooler_uses_session_pooling(manifests):
    # Transaction pooling breaks Odoo's prepared statements intermittently,
    # producing errors that are very hard to attribute.
    pooler = one(manifests, "Pooler")
    assert pooler["spec"]["pgbouncer"]["poolMode"] == "session"


def test_pooler_targets_the_read_write_service(manifests):
    assert one(manifests, "Pooler")["spec"]["type"] == "rw"


def test_postgres_declares_resources(manifests):
    resources = one(manifests, "Cluster")["spec"]["resources"]
    assert resources["requests"]["memory"] and resources["limits"]["memory"]


def test_transaction_pooling_is_rejected():
    # The chart must refuse a value that would silently corrupt Odoo sessions.
    try:
        helm_template({"postgres": {"pooler": {"poolMode": "transaction"}}})
    except AssertionError as exc:
        assert "session" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("expected transaction pooling to be rejected")


def test_scram_authentication_is_configured(manifests):
    params = one(manifests, "Cluster")["spec"]["postgresql"]["parameters"]
    assert params["password_encryption"] == "scram-sha-256"


def test_backup_is_configured_when_enabled():
    manifests = helm_template({
        "backup": {
            "enabled": True,
            "destinationPath": "s3://odoo-backups/acme",
            "endpointURL": "http://minio.storage:9000",
        },
    })
    cluster = one(manifests, "Cluster")
    assert cluster["spec"]["backup"]["barmanObjectStore"]["destinationPath"]


def test_backup_requires_a_destination():
    # Enabling backups without a destination would produce a cluster that
    # reports healthy while archiving nowhere.
    try:
        helm_template({"backup": {"enabled": True}})
    except AssertionError as exc:
        assert "destinationpath" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("expected a missing backup destination to fail rendering")


def test_no_backup_stanza_when_disabled(manifests):
    assert "backup" not in one(manifests, "Cluster")["spec"]


def test_monitoring_is_enabled(manifests):
    assert one(manifests, "Cluster")["spec"]["monitoring"]["enablePodMonitor"] is True
