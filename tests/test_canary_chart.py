from conftest import by_kind, helm_template, one


def test_canary_deployment_is_rendered(manifests):
    assert one(manifests, "Deployment", "-canary")["spec"]["replicas"] == 1


def test_canary_reads_its_password_from_a_file(manifests):
    container = one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]["containers"][0]
    for entry in container.get("env", []):
        assert "secretKeyRef" not in str(entry.get("valueFrom", {})), entry["name"]
    assert any(m["mountPath"] == "/etc/odoo-secrets" for m in container["volumeMounts"])


def test_canary_mounts_only_its_own_secret(manifests):
    # The other Odoo pods mount a projected bundle with the admin and database
    # passwords. The probe needs neither, so giving it them would turn a
    # compromised synthetic probe into a credential theft.
    volumes = one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]["volumes"]
    assert len(volumes) == 1
    volume = volumes[0]
    assert "projected" not in volume
    assert volume["secret"]["secretName"].endswith("-canary")
    assert volume["secret"]["defaultMode"] == 0o400


def test_canary_probes_the_service_not_a_pod(manifests):
    # Probing the Service exercises the same path a user takes through
    # kube-proxy; probing one pod would miss a partially broken rollout.
    env = {e["name"]: e.get("value")
           for e in one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]["containers"][0]["env"]}
    assert env["ODOO_URL"] == "http://acme-web:8069"


def test_canary_is_hardened(manifests):
    pod = one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]
    assert pod["automountServiceAccountToken"] is False
    assert pod["securityContext"]["runAsNonRoot"] is True
    security = pod["containers"][0]["securityContext"]
    assert security["readOnlyRootFilesystem"] is True
    assert security["capabilities"]["drop"] == ["ALL"]


def test_canary_egress_to_web_is_allowed(manifests):
    # Default-deny would otherwise make the probe report a healthy tenant down.
    names = {p["metadata"]["name"] for p in by_kind(manifests, "NetworkPolicy")}
    assert any("canary-to-web" in n for n in names)
    assert any("web-from-canary" in n for n in names)


def test_canary_metrics_port_is_named_for_scraping(manifests):
    ports = one(manifests, "Service", "-canary")["spec"]["ports"]
    assert ports[0]["name"] == "metrics" and ports[0]["port"] == 9101


def test_canary_can_be_disabled():
    manifests = helm_template({"canary": {"enabled": False}})
    assert not [m for m in manifests
                if m["kind"] == "Deployment" and m["metadata"]["name"].endswith("-canary")]
    assert not [p for p in by_kind(manifests, "NetworkPolicy")
                if "canary" in p["metadata"]["name"]]


def test_canary_can_read_its_projected_secret(manifests):
    # The projected volume is mode 0400 owned by root. Without a matching
    # fsGroup the container cannot read it and crash-loops on startup.
    pod = one(manifests, "Deployment", "-canary")["spec"]["template"]["spec"]
    security = pod["securityContext"]
    assert security.get("fsGroup") == security["runAsUser"], (
        "fsGroup must match runAsUser so the mounted secret is readable"
    )
