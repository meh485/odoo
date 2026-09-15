"""Assertions on the rendered restore-drill CronJob and its RBAC.

The drill is the one piece of custom logic no operator provides: CloudNativePG
makes backups declarative, not verified. These tests pin the properties that
keep it safe to run unattended in a live tenant namespace.
"""
from conftest import by_kind, helm_template, one

BACKUP = {
    "backup": {
        "enabled": True,
        "destinationPath": "s3://odoo-backups/acme",
        "endpointURL": "http://minio.storage.svc.cluster.local:9000",
    },
}


def drill(manifests):
    return one(manifests, "CronJob", "restore-drill")


def test_drill_is_not_rendered_without_backups(manifests):
    # A drill with nothing to restore would report a false failure forever.
    assert not [c for c in by_kind(manifests, "CronJob") if "restore-drill" in c["metadata"]["name"]]


def test_drill_is_scheduled_weekly():
    schedule = drill(helm_template(BACKUP))["spec"]["schedule"].split()
    assert len(schedule) == 5, "a CronJob schedule is five fields"
    assert schedule[4] != "*", "the drill must run on a named weekday, not every day"


def test_drill_does_not_collide_with_the_backup_window():
    manifests = helm_template(BACKUP)
    drill_hour = drill(manifests)["spec"]["schedule"].split()[1]
    # ScheduledBackup uses the six-field Go cron, so its hour is the third field.
    backup_hour = one(manifests, "ScheduledBackup")["spec"]["schedule"].split()[2]
    assert drill_hour != backup_hour, (
        f"drill at hour {drill_hour} collides with the backup at hour {backup_hour}"
    )


def test_drill_forbids_overlapping_runs():
    # Two restores at once would exhaust the namespace quota and could each
    # delete the other's scratch cluster.
    assert drill(helm_template(BACKUP))["spec"]["concurrencyPolicy"] == "Forbid"


def test_drill_cleans_up_finished_jobs():
    job = drill(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]
    assert job["ttlSecondsAfterFinished"], "finished jobs must be reaped automatically"


def test_drill_uses_its_own_service_account():
    pod = drill(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    assert pod["serviceAccountName"].endswith("-restore-drill")


def test_drill_holds_no_cluster_scoped_grant():
    manifests = helm_template(BACKUP)
    for kind in ("ClusterRole", "ClusterRoleBinding"):
        assert not by_kind(manifests, kind), (
            f"the drill must never hold a cluster-scoped {kind}"
        )


def test_drill_role_can_create_and_delete_clusters_in_its_own_namespace():
    role = one(helm_template(BACKUP), "Role", "restore-drill")
    assert role["metadata"]["namespace"] == "acme"
    rule = next(r for r in role["rules"] if "clusters" in r["resources"])
    assert "postgresql.cnpg.io" in rule["apiGroups"]
    assert {"create", "delete"} <= set(rule["verbs"])


def test_drill_role_uses_no_wildcards():
    role = one(helm_template(BACKUP), "Role", "restore-drill")
    for rule in role["rules"]:
        assert "*" not in rule.get("verbs", []), f"wildcard verb in {rule}"
        assert "*" not in rule.get("resources", []), f"wildcard resource in {rule}"
        assert "*" not in rule.get("apiGroups", []), f"wildcard apiGroup in {rule}"


def test_drill_role_cannot_read_arbitrary_secrets():
    # It needs its scratch cluster's own credential, no more.
    role = one(helm_template(BACKUP), "Role", "restore-drill")
    for rule in role["rules"]:
        if "secrets" in rule.get("resources", []):
            assert rule.get("resourceNames"), (
                "secret access must be limited to named resources"
            )
            assert not any("*" in name for name in rule["resourceNames"])


def test_drill_pod_is_hardened():
    pod = drill(helm_template(BACKUP))["spec"]["jobTemplate"]["spec"]["template"]["spec"]
    container = pod["containers"][0]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"]["readOnlyRootFilesystem"] is True
    assert container["securityContext"]["allowPrivilegeEscalation"] is False
    assert container["resources"]["requests"] and container["resources"]["limits"]
