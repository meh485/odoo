"""ArgoCD provisions tenants from git, so the committed ApplicationSet, the
project it references and the repository it points at are all asserted here.
"""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
ARGOCD = REPO / "platform" / "argocd"
APPSET = ARGOCD / "applicationset.yaml"
TENANTS = REPO / "tenants"


def appset() -> dict:
    return yaml.safe_load(APPSET.read_text())


def _slug(url: str) -> str:
    """owner/repo, from an https or ssh remote URL."""
    slug = re.sub(r"^(git@|ssh://git@|https://)", "", url.strip())
    slug = re.sub(r"^github\.com[:/]", "", slug)
    return slug.removesuffix(".git")


def test_the_applicationset_enables_argocd_ordering() -> None:
    # Without this the one-time Jobs render as Helm hooks, ArgoCD maps those to
    # PostSync, and the sync waits for a web Deployment that cannot be healthy
    # until the jobs have run.
    helm = appset()["spec"]["template"]["spec"]["source"]["helm"]
    parameters = {p["name"]: p["value"] for p in helm.get("parameters", [])}
    assert parameters.get("argocd.enabled") == "true"


def test_the_generator_uses_go_templates() -> None:
    # Without goTemplate, the controller does not substitute {{.tenant.name}}:
    # it tries to create an Application whose name is the literal placeholder,
    # and the API server rejects it.
    assert appset()["spec"].get("goTemplate") is True


def test_the_referenced_project_exists() -> None:
    # An Application pointing at a project that was never created fails to
    # sync, and nothing else in the repository would notice.
    projects = {
        document["metadata"]["name"]
        for path in ARGOCD.glob("*.yaml")
        for document in yaml.safe_load_all(path.read_text())
        if document and document.get("kind") == "AppProject"
    }
    assert appset()["spec"]["template"]["spec"]["project"] in projects


def test_argocd_points_at_the_repository_we_push_to() -> None:
    # Syncing from a different repository than the one this checkout pushes to
    # is a silent failure: the manifests under review and the manifests being
    # reconciled would not be the same ones.
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"], cwd=REPO, capture_output=True, text=True
    )
    if result.returncode != 0:
        pytest.skip("no origin remote to compare against")
    expected = _slug(result.stdout)

    git = next(g["git"] for g in appset()["spec"]["generators"] if "git" in g)
    source = appset()["spec"]["template"]["spec"]["source"]
    assert _slug(git["repoURL"]) == expected
    assert _slug(source["repoURL"]) == expected


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


def projects() -> dict:
    return {
        document["metadata"]["name"]: document
        for path in ARGOCD.glob("*.yaml")
        for document in yaml.safe_load_all(path.read_text())
        if document and document.get("kind") == "AppProject"
    }


def test_the_two_tiers_are_separate_projects() -> None:
    # One project for tenants and one for the cluster-scoped platform tier. The
    # platform project may write the namespace ArgoCD itself runs in, which
    # ArgoCD documents as admin-level access, so the tenant tier must never
    # share it.
    assert {"odoo", "platform"} <= set(projects())


def test_the_tenant_project_cannot_create_cluster_scoped_objects() -> None:
    # The tenant project's only cluster-scoped grant is the tenants' own
    # Namespaces. Anything else would hand the tenant tier cluster-wide reach.
    granted = {
        (entry["group"], entry["kind"])
        for entry in projects()["odoo"]["spec"]["clusterResourceWhitelist"]
    }
    assert granted == {("", "Namespace")}


def test_the_platform_project_never_grants_custom_resource_definitions() -> None:
    # Pruning a CRD deletes every custom resource of its kind, so the tenant
    # databases would go with CloudNativePG's. CRDs are installed once by the
    # bootstrap and stay unmanaged.
    granted = {
        (entry["group"], entry["kind"])
        for entry in projects()["platform"]["spec"]["clusterResourceWhitelist"]
    }
    assert ("apiextensions.k8s.io", "CustomResourceDefinition") not in granted


def test_tenant_applications_never_use_the_platform_project() -> None:
    assert appset()["spec"]["template"]["spec"]["project"] == "odoo"