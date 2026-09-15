"""The tenants/ directory is the source of truth for provisioning: one file per
customer, consumed by `make tenant` and by the ArgoCD ApplicationSet generator.
"""
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
TENANTS = REPO / "tenants"

FILES = sorted(TENANTS.glob("*.yaml"))
IDS = [path.stem for path in FILES]

FORBIDDEN_KEYS = {
    "accessKeyId",
    "secretAccessKey",
    "password",
    "admin_passwd",
    "canary_password",
}


def load(path: Path) -> dict:
    return yaml.safe_load(path.read_text())


def all_keys(node: object) -> list[str]:
    """Every key anywhere in the document, so a nested credential cannot hide."""
    found: list[str] = []
    if isinstance(node, dict):
        for key, value in node.items():
            found.append(key)
            found.extend(all_keys(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(all_keys(item))
    return found


def test_there_is_at_least_one_tenant() -> None:
    assert FILES, "no tenant values files"


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_tenant_name_matches_its_filename(path: Path) -> None:
    assert load(path)["tenant"]["name"] == path.stem


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_tenant_declares_a_hostname(path: Path) -> None:
    assert load(path)["tenant"]["hostname"]


def test_hostnames_are_unique() -> None:
    hostnames = [load(path)["tenant"]["hostname"] for path in FILES]
    assert len(hostnames) == len(set(hostnames)), "two tenants claim the same hostname"


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_tenants_commit_no_credentials(path: Path) -> None:
    # A credential belongs in a Secret the platform seeds, never in git.
    leaked = FORBIDDEN_KEYS.intersection(all_keys(load(path)))
    assert not leaked, f"{path.name} contains credential keys: {sorted(leaked)}"


@pytest.mark.parametrize("path", FILES, ids=IDS)
def test_backups_declare_a_destination(path: Path) -> None:
    backup = load(path).get("backup") or {}
    if backup.get("enabled"):
        assert backup.get("destinationPath"), f"{path.name} enables backups without a destination"
        assert backup.get("endpointURL"), f"{path.name} enables backups without an endpoint"