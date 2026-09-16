"""pytest asserts what the chart renders; the `helm test` hooks assert what the
cluster does once a tenant is running. These tests guard those hooks.
"""
from conftest import by_kind


def hook_pods(manifests) -> list[dict]:
    return [
        pod
        for pod in by_kind(manifests, "Pod")
        if "helm.sh/hook" in pod["metadata"].get("annotations", {})
    ]


def test_a_connection_test_exists(manifests) -> None:
    assert any("test-connection" in pod["metadata"]["name"] for pod in hook_pods(manifests))


def test_a_test_asserts_database_operations_are_denied(manifests) -> None:
    assert any("database-manager" in pod["metadata"]["name"] for pod in hook_pods(manifests))


def test_test_pods_are_hardened_like_everything_else(manifests) -> None:
    for pod in hook_pods(manifests):
        assert pod["spec"]["securityContext"]["runAsNonRoot"] is True
        container = pod["spec"]["containers"][0]
        assert container["securityContext"]["readOnlyRootFilesystem"] is True
        assert container["securityContext"]["allowPrivilegeEscalation"] is False


def test_test_pods_are_deleted_after_running(manifests) -> None:
    for pod in hook_pods(manifests):
        policy = pod["metadata"]["annotations"]["helm.sh/hook-delete-policy"]
        assert "hook-succeeded" in policy


def test_a_test_asserts_the_default_admin_password_is_rejected(manifests) -> None:
    pod = next(
        pod for pod in hook_pods(manifests)
        if "default-admin" in pod["metadata"]["name"]
    )
    args = " ".join(pod["spec"]["containers"][0]["args"])
    assert "-web:8069/web/session/authenticate" in args
    assert '"login": "admin"' in args
    assert '"password": "admin"' in args
    assert "AccessDenied" in args
    assert '"uid"' in args


def test_database_test_bypasses_the_gateway(manifests) -> None:
    # It must hit the web Service directly, or it proves nothing about list_db.
    pod = next(pod for pod in hook_pods(manifests) if "database-manager" in pod["metadata"]["name"])
    args = " ".join(pod["spec"]["containers"][0]["args"])
    assert "-web:8069/web/database/list" in args
    assert "AccessDenied" in args


def test_test_pods_can_reach_the_web_service(manifests) -> None:
    # Without a named allow the default-deny policy makes the hooks fail.
    names = {policy["metadata"]["name"] for policy in by_kind(manifests, "NetworkPolicy")}
    assert any("allow-test-to-web" in name for name in names)
    assert any("allow-web-from-test" in name for name in names)


def test_no_test_hook_uses_the_latest_tag(manifests) -> None:
    assert ":latest" not in str(hook_pods(manifests))