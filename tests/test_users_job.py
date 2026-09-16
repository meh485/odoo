import pytest
from conftest import by_kind, one


def test_a_users_job_exists(manifests):
    job = one(manifests, "Job", "odoo-users")
    assert job["spec"]["template"]["spec"]["restartPolicy"] == "Never"


def test_users_job_runs_after_schema_initialisation(manifests):
    # Setting a password on a database with no res_users table fails.
    init = one(manifests, "Job", "odoo-init")["metadata"]["annotations"]
    users = one(manifests, "Job", "odoo-users")["metadata"]["annotations"]
    assert int(users["helm.sh/hook-weight"]) > int(init["helm.sh/hook-weight"])


def test_users_job_takes_no_password_from_argv_or_env(manifests):
    # A password in argv is visible in the process list and in
    # `kubectl describe job` output; in env it shows in describe as well.
    container = one(manifests, "Job", "odoo-users")["spec"]["template"]["spec"]["containers"][0]
    joined = " ".join(container.get("args", []) + container.get("command", []))
    assert "/etc/odoo-secrets" in joined or "password" not in joined.lower()
    for entry in container.get("env", []):
        assert "secretKeyRef" not in str(entry.get("valueFrom", {})), entry["name"]


def test_the_chart_does_not_generate_the_canary_secret(manifests):
    # Same rule as the admin password: the Secret is created out of band and
    # only referenced, so a render never depends on cluster state.
    rendered = {secret["metadata"]["name"] for secret in by_kind(manifests, "Secret")}
    assert not {name for name in rendered if name.endswith("-canary")}, (
        f"the chart renders the canary Secret: {sorted(rendered)}"
    )


def test_the_probe_mounts_the_canary_secret_by_name(manifests):
    pod = one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]
    mounted = {v["secret"]["secretName"] for v in pod["volumes"] if "secret" in v}
    assert mounted == {"acme-canary"}


@pytest.mark.parametrize("job", ["odoo-init", "odoo-users"])
def test_jobs_are_hardened(manifests, job):
    pod = one(manifests, "Job", job)["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["containers"][0]["securityContext"]["readOnlyRootFilesystem"] is True


def test_users_job_mounts_both_credentials(manifests):
    # The job sets the admin password and creates the canary account, so it
    # needs both secrets in one directory.
    pod = one(manifests, "Job", "odoo-users")["spec"]["template"]["spec"]
    projected = [v for v in pod["volumes"] if "projected" in v][0]
    paths = {
        item["path"]
        for source in projected["projected"]["sources"]
        for item in source["secret"]["items"]
    }
    assert {"admin_passwd", "canary_password", "db_password"} <= paths


def test_users_script_is_not_a_hook(manifests):
    # A hook ConfigMap at the same weight as the job that mounts it races, and
    # the job fails with MountVolume.SetUp failed: configmap not found.
    script = one(manifests, "ConfigMap", "odoo-users-script")
    annotations = script["metadata"].get("annotations", {})
    assert "helm.sh/hook" not in annotations, (
        "the script ConfigMap must be a normal resource so it exists before "
        "the post-install hook job mounts it"
    )


def test_every_configmap_a_hook_job_mounts_is_a_normal_resource(manifests):
    # Generalises the rule above to any future hook job.
    normal_configmaps = {
        m["metadata"]["name"] for m in manifests
        if m["kind"] == "ConfigMap" and "helm.sh/hook" not in m["metadata"].get("annotations", {})
    }
    for job in [m for m in manifests if m["kind"] == "Job"]:
        if "helm.sh/hook" not in job["metadata"].get("annotations", {}):
            continue
        for volume in job["spec"]["template"]["spec"]["volumes"]:
            if "configMap" in volume:
                name = volume["configMap"]["name"]
                assert name in normal_configmaps, (
                    f"hook job {job['metadata']['name']} mounts ConfigMap {name}, "
                    "which is not a normal resource and may not exist yet"
                )
