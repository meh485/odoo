import pathlib

from conftest import helm_template

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "charts" / "odoo-tenant" / "templates"


def test_chart_renders(manifests):
    assert manifests, "chart rendered no manifests"


def test_no_template_generates_a_credential_at_render_time():
    # A credential produced during a render makes the manifests depend on
    # cluster state: Helm's lookup cannot run under Argo CD, so the value would
    # change on every sync, the application would never report Synced, and
    # whatever consumes it would be rotated. Every credential in this chart is
    # referenced from a Secret created out of band instead -- seeded by
    # scripts locally, filled by External Secrets in production.
    offenders: dict[str, list[str]] = {}
    for path in sorted(TEMPLATES.rglob("*.yaml")):
        text = path.read_text()
        for function in ("randAlphaNum", "randAlpha", 'lookup "v1"'):
            if function in text:
                offenders.setdefault(path.name, []).append(function)
    assert not offenders, f"templates generate a credential at render time: {offenders}"


# Cluster-scoped kinds have no namespace; setting one on them is rejected
# by some validators and silently ignored by others.
CLUSTER_SCOPED = {"Namespace", "GatewayClass", "ClusterRole", "ClusterRoleBinding"}


def test_every_namespaced_manifest_is_scoped_to_the_tenant(manifests):
    for manifest in manifests:
        if manifest["kind"] in CLUSTER_SCOPED:
            continue
        namespace = manifest["metadata"].get("namespace")
        assert namespace == "acme", (
            f"{manifest['kind']}/{manifest['metadata']['name']} "
            f"has namespace {namespace!r}, expected 'acme'"
        )


def test_cluster_scoped_manifests_declare_no_namespace(manifests):
    for manifest in manifests:
        if manifest["kind"] in CLUSTER_SCOPED:
            assert "namespace" not in manifest["metadata"], (
                f"{manifest['kind']}/{manifest['metadata']['name']} is cluster-scoped "
                "but declares a namespace"
            )


def test_every_manifest_carries_the_tenant_label(manifests):
    for manifest in manifests:
        labels = manifest["metadata"].get("labels", {})
        assert labels.get("app.kubernetes.io/instance") == "acme"


def test_no_manifest_uses_a_latest_tag(manifests):
    assert ":latest" not in str(manifests)


def test_tenant_name_is_validated():
    # Targets tenant.name rather than the release name, because Helm rejects
    # an invalid release name itself and would mask the chart's own check.
    try:
        helm_template({"tenant": {"name": "Bad_Name"}})
    except AssertionError as exc:
        assert "invalid" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("expected an invalid tenant name to fail rendering")


def test_blank_tenant_name_falls_back_to_the_release_name(manifests):
    # A blank name must not render objects with an empty or colliding identity.
    namespace = [m for m in manifests if m["kind"] == "Namespace"][0]
    assert namespace["metadata"]["name"] == "acme"
