import pytest
from conftest import by_kind, helm_template, one


def test_web_and_cron_are_separate_deployments(manifests):
    names = {d["metadata"]["name"] for d in manifests if d["kind"] == "Deployment"}
    assert any(n.endswith("-web") for n in names)
    assert any(n.endswith("-cron") for n in names)


def test_web_runs_no_cron_threads(manifests):
    # A scheduled job running inside the web process competes with user
    # requests for the same workers.
    web = one(manifests, "Deployment", "-web")
    env = {e["name"]: e.get("value") for e in web["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["ODOO_MAX_CRON_THREADS"] == "0"


def test_cron_runs_no_http_listener(manifests):
    cron = one(manifests, "Deployment", "-cron")
    assert "--no-http" in cron["spec"]["template"]["spec"]["containers"][0].get("args", [])


def test_only_one_cron_replica(manifests):
    # Two cron containers would run every scheduled job twice.
    assert one(manifests, "Deployment", "-cron")["spec"]["replicas"] == 1


@pytest.mark.parametrize("suffix", ["-web", "-cron"])
def test_workloads_are_hardened(manifests, suffix):
    pod = one(manifests, "Deployment", suffix)["spec"]["template"]["spec"]
    assert pod["securityContext"]["runAsNonRoot"] is True
    assert pod["securityContext"]["seccompProfile"]["type"] == "RuntimeDefault"
    security = pod["containers"][0]["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["readOnlyRootFilesystem"] is True
    assert security["capabilities"]["drop"] == ["ALL"]


@pytest.mark.parametrize("suffix", ["-web", "-cron"])
def test_no_password_reaches_an_environment_variable(manifests, suffix):
    # Environment variables appear in `kubectl describe pod` and in crash
    # dumps. Secrets must arrive as mounted files.
    container = one(manifests, "Deployment", suffix)["spec"]["template"]["spec"]["containers"][0]
    for entry in container.get("env", []):
        assert "secretKeyRef" not in str(entry.get("valueFrom", {})), (
            f"{entry['name']} takes its value from a secret via the environment"
        )


@pytest.mark.parametrize("suffix", ["-web", "-cron"])
def test_workloads_declare_resources(manifests, suffix):
    resources = one(manifests, "Deployment", suffix)["spec"]["template"]["spec"]["containers"][0]["resources"]
    assert resources["requests"]["memory"] and resources["limits"]["memory"]


def test_web_declares_a_startup_probe(manifests):
    # Odoo is slow to boot. Without a startup probe the liveness probe kills
    # it mid-initialisation and the pod never becomes ready.
    container = one(manifests, "Deployment", "-web")["spec"]["template"]["spec"]["containers"][0]
    assert container["startupProbe"]
    assert container["readinessProbe"]
    assert container["livenessProbe"]


def test_web_carries_the_component_label_the_policy_selects(manifests):
    # The gateway ingress policy selects app.kubernetes.io/component=web.
    # A mismatch here silently leaves the tenant unreachable.
    labels = one(manifests, "Deployment", "-web")["spec"]["template"]["metadata"]["labels"]
    assert labels["app.kubernetes.io/component"] == "web"


def test_filestore_is_persistent(manifests):
    pvc = one(manifests, "PersistentVolumeClaim", "filestore")
    assert pvc["spec"]["resources"]["requests"]["storage"]


def test_config_disables_the_database_manager(manifests):
    rendered = one(manifests, "ConfigMap", "odoo-config")["data"]["odoo.conf.template"]
    assert "list_db = False" in rendered
    assert "proxy_mode = True" in rendered


def test_config_contains_no_password(manifests):
    rendered = one(manifests, "ConfigMap", "odoo-config")["data"]["odoo.conf.template"]
    assert "db_password" not in rendered, "the ConfigMap must never carry a password"


def test_service_exposes_web_and_longpolling(manifests):
    ports = {p["port"] for p in one(manifests, "Service", "-web")["spec"]["ports"]}
    assert {8069, 8072} <= ports


@pytest.mark.parametrize("suffix", ["-web", "-cron"])
def test_workloads_do_not_mount_a_service_account_token(manifests, suffix):
    # Odoo never calls the Kubernetes API. Dropping the token removes a
    # credential from the pod, and its mount path (/var/run/secrets/...)
    # collides with any volume mounted at /run/secrets on a read-only rootfs.
    pod = one(manifests, "Deployment", suffix)["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False


@pytest.mark.parametrize("suffix", ["-web", "-cron"])
def test_secrets_are_not_mounted_under_run_secrets(manifests, suffix):
    pod = one(manifests, "Deployment", suffix)["spec"]["template"]["spec"]
    for mount in pod["containers"][0]["volumeMounts"]:
        assert not mount["mountPath"].startswith("/run/secrets"), (
            "mounting at /run/secrets shadows the kubelet's service account "
            "token path and prevents the container from starting"
        )


def test_the_chart_does_not_generate_the_admin_secret(manifests):
    # A render-time generated password makes the manifests depend on cluster
    # state. Argo CD renders without Helm's lookup, so the value would be
    # regenerated on every sync, the app would never leave OutOfSync, and the
    # live password would change each time. The Secret is created out of band
    # (a seed script locally, External Secrets in production) and only
    # referenced here.
    rendered = {
        secret["metadata"]["name"] for secret in by_kind(manifests, "Secret")
    }
    assert not {name for name in rendered if name.endswith("-odoo-admin")}, (
        f"the chart renders the admin Secret: {sorted(rendered)}"
    )


def test_the_credentials_volume_references_the_admin_secret(manifests):
    assert "acme-odoo-admin" in _credential_secret_names(manifests)


def test_the_admin_secret_name_can_be_overridden():
    manifests = helm_template(
        {"odoo": {"adminPassword": {"existingSecret": "vault-managed-admin"}}}
    )
    assert "vault-managed-admin" in _credential_secret_names(manifests)


def _credential_secret_names(manifests) -> set[str]:
    pod = one(manifests, "Deployment", "-web")["spec"]["template"]["spec"]
    volume = next(v for v in pod["volumes"] if v["name"] == "db-credentials")
    return {source["secret"]["name"] for source in volume["projected"]["sources"]}


def test_odoo_points_at_the_pooler_service_that_actually_exists(manifests):
    # CloudNativePG names the pooler Service after the Pooler resource. An
    # invented suffix renders fine and fails at runtime with a DNS error, so
    # the two names are compared against each other rather than hardcoded.
    pooler_name = one(manifests, "Pooler")["metadata"]["name"]
    config = one(manifests, "ConfigMap", "odoo-config")["data"]["odoo.conf.template"]
    host = [l.split("=", 1)[1].strip() for l in config.splitlines()
            if l.strip().startswith("db_host")][0]
    assert host == pooler_name, f"db_host {host!r} does not match Pooler {pooler_name!r}"


def test_odoo_does_not_connect_directly_to_postgres(manifests):
    # Bypassing the pooler would exhaust Postgres connections as workers scale.
    config = one(manifests, "ConfigMap", "odoo-config")["data"]["odoo.conf.template"]
    host = [l.split("=", 1)[1].strip() for l in config.splitlines()
            if l.strip().startswith("db_host")][0]
    assert not host.endswith("-db-rw"), "Odoo must connect through the pooler"


def test_an_init_job_creates_the_odoo_schema(manifests):
    # CloudNativePG creates an empty database. Without initialisation every
    # request fails with KeyError: 'ir.http' while the pod reports Running.
    job = one(manifests, "Job", "odoo-init")
    args = job["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "-i" in args and "base" in args
    assert "--stop-after-init" in args


def test_init_job_installs_no_demo_data(manifests):
    # Demo data in a customer database is a production incident discovered
    # later by an accountant.
    args = one(manifests, "Job", "odoo-init")["spec"]["template"]["spec"]["containers"][0]["args"]
    assert "--without-demo=all" in args


def test_quota_leaves_headroom_for_a_rolling_update(manifests):
    # A quota that exactly fits steady state rejects the surge pod, and the
    # rollout hangs with the old ReplicaSet still serving.
    quota = one(manifests, "ResourceQuota")["spec"]["hard"]
    web = one(manifests, "Deployment", "-web")
    cron = one(manifests, "Deployment", "-cron")
    cluster = one(manifests, "Cluster")

    def cpu(value: str) -> float:
        return float(value[:-1]) / 1000 if value.endswith("m") else float(value)

    replicas = web["spec"]["replicas"]
    web_cpu = cpu(web["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"])
    cron_cpu = cpu(cron["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["cpu"])
    pg_cpu = cpu(cluster["spec"]["resources"]["limits"]["cpu"]) * cluster["spec"]["instances"]
    surge = web_cpu  # maxSurge: 1

    needed = replicas * web_cpu + cron_cpu + pg_cpu + surge
    assert cpu(quota["limits.cpu"]) >= needed, (
        f"quota limits.cpu={quota['limits.cpu']} cannot fit steady state plus "
        f"one surge pod ({needed} CPU)"
    )


def test_web_rollout_bounds_its_surge(manifests):
    strategy = one(manifests, "Deployment", "-web")["spec"]["strategy"]["rollingUpdate"]
    assert strategy["maxSurge"] == 1
