"""ArgoCD is not run locally, but the ApplicationSet is committed so the
provisioning mechanism is reviewable and testable.
"""
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
APPSET = REPO / "platform" / "argocd" / "applicationset.yaml"
TENANTS = REPO / "tenants"


def appset() -> dict:
    return yaml.safe_load(APPSET.read_text())


def test_generator_discovers_tenants_from_git() -> None:
    generators = appset()["spec"]["generators"]
    git = next((g["git"] for g in generators if "git" in g), None)
    assert git, "tenants must come from git, not a static list"
    assert any(entry["path"].endswith("tenants/*.yaml") for entry in git["files"])


def test_application_is_named_per_tenant() -> None:
    assert "{{.tenant.name}}" in appset()["spec"]["template"]["metadata"]["name"]


def test_applications_do_not_auto_prune() -> None:
    # Pruning a namespace deletes its PersistentVolumeClaims.
    automated = appset()["spec"]["template"]["spec"]["syncPolicy"]["automated"]
    assert automated.get("prune") is False


def test_sync_policy_does_not_disable_validation() -> None:
    options = appset()["spec"]["template"]["spec"]["syncPolicy"].get("syncOptions", [])
    assert "Validate=false" not in options


def test_every_tenant_declares_a_hostname() -> None:
    files = list(TENANTS.glob("*.yaml"))
    assert files, "no tenant values files"
    for path in files:
        assert yaml.safe_load(path.read_text())["tenant"]["hostname"]