"""Helpers for rendering the chart and asserting on the result.

Tests run `helm template` and parse the output, so they assert on what
Kubernetes would actually receive rather than on template source text.
"""
import subprocess
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CHART = REPO_ROOT / "charts" / "odoo-tenant"


def helm_template(values: dict | None = None, tenant: str = "acme") -> list[dict]:
    """Render the chart and return every manifest as a parsed dict."""
    args = ["helm", "template", tenant, str(CHART), "--namespace", tenant]
    args += ["--set", f"tenant.name={tenant}", "--set", "tenant.hostname=acme.odoo.local"]
    if values:
        for key, value in _flatten(values):
            args += ["--set", f"{key}={value}"]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"helm template failed:\n{result.stderr}")
    return [doc for doc in yaml.safe_load_all(result.stdout) if doc]


def _flatten(values: dict, prefix: str = ""):
    for key, value in values.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            yield from _flatten(value, path)
        else:
            yield path, value


def by_kind(manifests: list[dict], kind: str) -> list[dict]:
    return [m for m in manifests if m.get("kind") == kind]


def one(manifests: list[dict], kind: str, name_contains: str = "") -> dict:
    matches = [
        m for m in by_kind(manifests, kind)
        if name_contains in m["metadata"]["name"]
    ]
    assert len(matches) == 1, (
        f"expected exactly one {kind} matching {name_contains!r}, "
        f"found {[m['metadata']['name'] for m in matches]}"
    )
    return matches[0]


@pytest.fixture(scope="module")
def manifests() -> list[dict]:
    return helm_template()
