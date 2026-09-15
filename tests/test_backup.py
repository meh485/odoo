from conftest import helm_template, one


BACKUP_VALUES = {
    "backup": {
        "enabled": True,
        "destinationPath": "s3://odoo-backups/acme",
        "endpointURL": "http://minio.storage.svc.cluster.local:9000",
    },
}


def test_scheduled_backup_is_rendered():
    schedule = one(helm_template(BACKUP_VALUES), "ScheduledBackup")
    assert schedule["spec"]["cluster"]["name"] == "acme-db"


def test_backup_schedule_is_a_six_field_cron():
    # CloudNativePG uses the Go cron format, which includes seconds. A
    # five-field entry is accepted and runs at the wrong time.
    schedule = one(helm_template(BACKUP_VALUES), "ScheduledBackup")["spec"]["schedule"]
    assert len(schedule.split()) == 6, f"{schedule!r} is not a six-field cron expression"


def test_backup_credentials_are_a_secret_not_inline():
    cluster = one(helm_template(BACKUP_VALUES), "Cluster")
    store = cluster["spec"]["backup"]["barmanObjectStore"]
    assert store["s3Credentials"]["accessKeyId"]["name"]
    assert "accessKeyId" not in str(store.get("data", {}))


def test_wal_and_data_are_both_compressed():
    store = one(helm_template(BACKUP_VALUES), "Cluster")["spec"]["backup"]["barmanObjectStore"]
    assert store["wal"]["compression"]
    assert store["data"]["compression"]


def test_retention_is_declared():
    assert one(helm_template(BACKUP_VALUES), "Cluster")["spec"]["backup"]["retentionPolicy"]