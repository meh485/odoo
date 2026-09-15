#!/usr/bin/env python3
"""Synthetic Odoo probe: authenticate, then read a record.

Exposes Prometheus metrics on :9101.

An HTTP check on /web/health is not sufficient, and that is an observed fact
about this stack rather than a general claim: on this very cluster /web/health
returned 200 while the database had no schema and every real request failed
with KeyError: 'ir.http'. Authenticating over JSON-RPC and then reading a
record exercises the database, the session store and the ORM in one probe.

JSON-RPC rather than the HTML login form, because it avoids CSRF handling.
"""
from __future__ import annotations

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import requests
from prometheus_client import Gauge, start_http_server

CANARY_SUCCESS = Gauge("odoo_canary_success", "Whether the last probe succeeded.", ["tenant"])
CANARY_LOGIN = Gauge("odoo_canary_login_duration_seconds", "Login round trip duration.", ["tenant"])
CANARY_READ = Gauge("odoo_canary_read_duration_seconds", "Record read duration.", ["tenant"])
CANARY_RUN = Gauge("odoo_canary_last_run_timestamp_seconds", "Unix time of the last probe.", ["tenant"])


@dataclass(frozen=True)
class ProbeResult:
    success: bool
    login_seconds: float = 0.0
    read_seconds: float = 0.0
    error: str = ""


def read_secret(path: Path) -> str:
    """Read a secret file, exiting non-zero if it is missing or empty.

    Failing to start is correct here. A probe that runs with no credential
    reports the tenant as down and buries the real cause.
    """
    try:
        value = path.read_text().strip()
    except OSError as exc:
        sys.exit(f"cannot read secret {path}: {exc}")
    if not value:
        sys.exit(f"secret {path} is empty")
    return value


def _rpc(session, url: str, payload: dict, timeout: float):
    response = session.post(url, json=payload, timeout=timeout)
    if response.status_code != 200:
        raise RuntimeError(f"HTTP {response.status_code} from {url}")
    body = response.json()
    if "error" in body:
        raise RuntimeError(str(body["error"].get("message", body["error"])))
    return body.get("result")


def probe(session, base_url: str, database: str, login: str, password: str,
          timeout: float = 15.0) -> ProbeResult:
    """Authenticate over JSON-RPC and read one record."""
    try:
        started = time.monotonic()
        result = _rpc(session, f"{base_url}/web/session/authenticate", {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {"db": database, "login": login, "password": password},
        }, timeout)
        login_seconds = time.monotonic() - started

        # Odoo answers HTTP 200 with uid null on a rejected login.
        if not isinstance(result, dict) or not result.get("uid"):
            return ProbeResult(False, login_seconds, 0.0, "authentication returned no uid")

        started = time.monotonic()
        records = _rpc(session, f"{base_url}/web/dataset/call_kw", {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": "res.users",
                "method": "search_read",
                "args": [[["id", "=", result["uid"]]], ["id", "login"]],
                "kwargs": {"limit": 1},
            },
        }, timeout)
        read_seconds = time.monotonic() - started

        if not records:
            return ProbeResult(False, login_seconds, read_seconds, "record read returned no rows")
        return ProbeResult(True, login_seconds, read_seconds)
    except Exception as exc:  # noqa: BLE001 - any failure is a failed probe
        # Scrub the credential: this string is logged and could otherwise leak
        # the password into stdout on an authentication error.
        message = str(exc).replace(password, "<redacted>") if password else str(exc)
        return ProbeResult(False, error=message)


def main() -> int:
    tenant = os.environ["TENANT"]
    base_url = os.environ.get("ODOO_URL", "http://odoo-web:8069")
    database = os.environ.get("DB_NAME", tenant)
    login = os.environ.get("CANARY_LOGIN", "canary")
    interval = float(os.environ.get("CANARY_INTERVAL_SECONDS", "60"))
    password = read_secret(Path(os.environ.get("SECRETS_PATH", "/etc/odoo-secrets")) / "canary_password")

    start_http_server(9101)
    session = requests.Session()

    # Publish a value immediately so the metric exists before the first probe
    # completes; an absent series and a failing one look different to alerts.
    CANARY_SUCCESS.labels(tenant=tenant).set(0)

    while True:
        result = probe(session, base_url, database, login, password)
        CANARY_SUCCESS.labels(tenant=tenant).set(1 if result.success else 0)
        CANARY_LOGIN.labels(tenant=tenant).set(result.login_seconds)
        CANARY_READ.labels(tenant=tenant).set(result.read_seconds)
        CANARY_RUN.labels(tenant=tenant).set(time.time())
        if not result.success:
            print(f"canary failed for {tenant}: {result.error}", file=sys.stderr, flush=True)
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
