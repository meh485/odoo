"""Fixtures for tests that assert the live cluster.

The unit tests render the chart and assert on what Kubernetes would receive.
These tests are the other half: they ask the running platform whether it is
actually working. `make e2e` is the entry point.
"""
from __future__ import annotations

import json
import subprocess
import urllib.parse
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PROMETHEUS_PROXY = (
    "/api/v1/namespaces/monitoring/services/"
    "kube-prometheus-stack-prometheus:9090/proxy"
)
ALERTMANAGER_PROXY = (
    "/api/v1/namespaces/monitoring/services/"
    "kube-prometheus-stack-alertmanager:9093/proxy"
)


def kubectl(*args: str, stdin: str | None = None, timeout: int = 60) -> str:
    result = subprocess.run(
        ["kubectl", *args],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if result.returncode != 0:
        raise AssertionError(f"kubectl {' '.join(args)} failed:\n{result.stderr}")
    return result.stdout


def kubectl_json(*args: str) -> dict:
    return json.loads(kubectl(*args, "-o", "json") or "{}")


def kubectl_ok(*args: str, timeout: int = 60) -> str | None:
    """Run kubectl, returning None instead of raising when it fails.

    Used for polling an object that may legitimately not exist yet.
    """
    result = subprocess.run(
        ["kubectl", *args], capture_output=True, text=True, timeout=timeout
    )
    return result.stdout if result.returncode == 0 else None


def raw_json(path: str) -> dict:
    """Fetch a JSON document from an API-server proxy path.

    `kubectl get --raw` rejects `-o json`, so this cannot reuse kubectl_json.
    """
    return json.loads(kubectl("get", "--raw", path) or "{}")


def helm_json(*args: str) -> list[dict]:
    result = subprocess.run(
        ["helm", *args, "-o", "json"], capture_output=True, text=True, timeout=60
    )
    if result.returncode != 0:
        raise AssertionError(f"helm {' '.join(args)} failed:\n{result.stderr}")
    return json.loads(result.stdout or "[]")


@pytest.fixture(scope="session", autouse=True)
def cluster() -> None:
    """Skip the suite rather than fail it when no cluster is reachable."""
    try:
        kubectl("get", "--raw", f"{PROMETHEUS_PROXY}/-/ready", timeout=20)
    except (AssertionError, subprocess.SubprocessError) as exc:
        pytest.skip(f"no reachable cluster with Prometheus: {exc}")


@pytest.fixture(scope="session")
def tenants() -> list[str]:
    """Tenants that are actually deployed, not merely declared in tenants/.

    Discovered from the label on the namespace rather than from `helm list`.
    Intersecting with Helm releases was how this fixture used to work, and it
    meant every tenant ArgoCD created was skipped: the suite stayed green while
    one of them was serving nothing but 500s.
    """
    declared = {path.stem for path in (REPO_ROOT / "tenants").glob("*.yaml")}
    deployed = {
        item["metadata"]["name"]
        for item in kubectl_json(
            "get", "namespaces", "-l", "app.kubernetes.io/name=odoo"
        ).get("items", [])
    }
    return sorted(declared & deployed)


@pytest.fixture(scope="session")
def query():
    """Run an instant PromQL query and return the result vector."""

    def _query(expression: str) -> list[dict]:
        encoded = urllib.parse.quote(expression)
        path = f"{PROMETHEUS_PROXY}/api/v1/query?query={encoded}"
        return json.loads(kubectl("get", "--raw", path))["data"]["result"]

    return _query
