"""The filestore is the second store Odoo keeps. A database-only backup restores
a tenant whose attachments are all broken, so these tests pin the properties of
the restic job that captures it.
"""
from conftest import by_kind, helm_template, one

BACKUP = {
    "backup": {
        "enabled": True,
        "destinationPath": "s3://odoo-backups/acme",
        "endpointURL": "http://minio.storage.svc.cluster.local:9000",
        "filestore": {
            "enabled": True,
            "repository": "s3:http://minio.storage.svc.cluster.local:9000/odoo-backups/acme-filestore",
        },
    },
}


def job(manifests):
    return one(manifests, "CronJob", "filestore-backup")


def test_no_filestore_job_without_backups(manifests):
    assert not [c for c in by_kind(manifests, "CronJob") if "filestore-backup" in c["metadata"]["name"]]


def test_no_filestore_job_when_disabled():
    manifests = helm_template({"backup": {"enabled": True, "destinationPath": "s3://b/acme",
                                          "endpointURL": "http://m:9000", "filestore": {"enabled": False}}})
    assert not [c for c in by_kind(manifests, "CronJob") if "filestore-backup" in c["metadata"]["name"]]


def test_filestore_job_is_scheduled():
    schedule = job(helm_template(BACKUP))["spec"]["schedule"].split()
    assert len(schedule) == 5, "a CronJob schedule is five fields"


def test_filestore_job_forbids_overlapping_runs():
    assert job(helm_template(BACKUP))["spec"]["concurrencyPolicy"] == "Forbid"


def test_filestore_job_reaps_finished_jobs():
    assert job(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["ttlSecondsAfterFinished"]


def test_filestore_job_mounts_the_filestore_read_only():
    pod = job(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    mount = next(m for m in pod["containers"][0]["volumeMounts"] if m["mountPath"] == "/var/lib/odoo")
    assert mount["readOnly"] is True
    volume = next(v for v in pod["volumes"] if v["name"] == mount["name"])
    assert volume["persistentVolumeClaim"]["claimName"] == "acme-filestore"


def test_filestore_job_never_takes_a_secret_from_the_environment():
    pod = job(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    for entry in pod["containers"][0].get("env", []):
        assert "secretKeyRef" not in str(entry.get("valueFrom", {}))
    for volume in pod["volumes"]:
        if "secret" in volume:
            assert volume["secret"].get("defaultMode") == 0o400


def test_filestore_job_mounts_both_credentials_as_files():
    pod = job(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    secret_names = {v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v}
    assert "acme-backup-credentials" in secret_names
    assert "acme-restic" in secret_names


def test_restic_password_secret_is_rendered_and_preserved_across_upgrades():
    import pathlib
    secret = one(helm_template(BACKUP), "Secret", "restic")
    assert secret["data"]["restic_password"]
    source = pathlib.Path("charts/odoo-tenant/templates/filestore-backup-secret.yaml").read_text()
    assert "lookup" in source, "the restic password must survive an upgrade"


def test_filestore_job_is_hardened():
    pod = job(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["resources"]["requests"] and container["resources"]["limits"]


def test_no_filestore_job_uses_the_latest_tag():
    assert ":latest" not in str(helm_template(BACKUP))


def test_backup_pod_may_reach_object_storage():
    # Without a named egress allow the default-deny policy leaves the job
    # unable to archive anything.
    policies = by_kind(helm_template(BACKUP), "NetworkPolicy")
    egress = next(p for p in policies if "filestore-backup" in p["metadata"]["name"])
    ports = {port["port"] for rule in egress["spec"]["egress"] for port in rule["ports"]}
    assert 9000 in ports
