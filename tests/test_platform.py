"""Checks on the platform-owned manifests in platform/, which are applied with
kubectl rather than rendered by Helm."""
from pathlib import Path

import yaml

PLATFORM = Path(__file__).resolve().parents[1] / "platform" / "gateway"


def load(name: str) -> dict:
    return yaml.safe_load((PLATFORM / name).read_text())


def test_gatewayclass_points_at_an_envoyproxy_that_exists():
    # A parametersRef naming a missing EnvoyProxy leaves the GatewayClass
    # accepted but unconfigured, which is hard to spot after the fact.
    ref = load("gatewayclass.yaml")["spec"]["parametersRef"]
    proxy = load("envoyproxy.yaml")
    assert ref["name"] == proxy["metadata"]["name"]
    assert ref["namespace"] == proxy["metadata"]["namespace"]
    assert ref["kind"] == proxy["kind"]


def test_gateway_uses_the_declared_gatewayclass():
    assert load("gateway.yaml")["spec"]["gatewayClassName"] == load("gatewayclass.yaml")["metadata"]["name"]


def test_gateway_is_not_built_on_a_retired_controller():
    # ingress-nginx entered retirement in March 2026.
    controller = load("gatewayclass.yaml")["spec"]["controllerName"]
    assert "nginx" not in controller


def test_envoy_is_pinned_where_the_port_mapping_lives():
    # The generated Service uses externalTrafficPolicy: Local, so only nodes
    # running an Envoy pod answer on the NodePort. Without this pin, traffic
    # reaches a node with no local endpoint and is silently dropped.
    pod = load("envoyproxy.yaml")["spec"]["provider"]["kubernetes"]["envoyDeployment"]["pod"]
    assert pod["nodeSelector"]["kubernetes.io/hostname"]
    assert any(t["key"].startswith("node-role.kubernetes.io/control-plane")
               for t in pod["tolerations"])


def test_gateway_terminates_tls():
    listeners = {l["name"]: l for l in load("gateway.yaml")["spec"]["listeners"]}
    assert "https" in listeners
    tls = listeners["https"]["tls"]
    assert tls["mode"] == "Terminate"
    assert tls["certificateRefs"][0]["name"]


def test_plain_http_only_redirects():
    # Defence in depth: even if a tenant route attached to the HTTP listener,
    # the platform redirect answers first.
    route = load("https-redirect.yaml")
    rule = route["spec"]["rules"][0]
    assert "backendRefs" not in rule, "the HTTP listener must not proxy to any backend"
    redirect = rule["filters"][0]["requestRedirect"]
    assert redirect["scheme"] == "https"
    assert redirect["statusCode"] == 301


def test_redirect_route_binds_the_http_listener():
    assert load("https-redirect.yaml")["spec"]["parentRefs"][0]["sectionName"] == "http"
