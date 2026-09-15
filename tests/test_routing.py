from conftest import one


def test_httproute_binds_the_tenant_hostname(manifests):
    route = one(manifests, "HTTPRoute")
    assert route["spec"]["hostnames"] == ["acme.odoo.local"]


def test_httproute_references_the_shared_gateway(manifests):
    parent = one(manifests, "HTTPRoute")["spec"]["parentRefs"][0]
    assert parent["name"]
    # The Gateway is owned by the platform team in its own namespace; the
    # tenant owns only its route. That split is why Gateway API fits here.
    assert parent["namespace"] == "envoy-gateway-system"


def test_websocket_path_routes_to_the_longpolling_port(manifests):
    rules = one(manifests, "HTTPRoute")["spec"]["rules"]
    websocket = [
        r for r in rules
        if any(m.get("path", {}).get("value", "").startswith("/websocket")
               for m in r.get("matches", []))
    ]
    assert websocket, "no /websocket rule"
    assert websocket[0]["backendRefs"][0]["port"] == 8072


def test_websocket_rule_allows_a_long_lived_connection(manifests):
    rules = one(manifests, "HTTPRoute")["spec"]["rules"]
    websocket = [
        r for r in rules
        if any(m.get("path", {}).get("value", "").startswith("/websocket")
               for m in r.get("matches", []))
    ][0]
    # A default 15s timeout silently breaks Odoo's long-polling bus, which
    # presents as the UI simply not updating rather than as an error.
    assert websocket["timeouts"]["request"] == "3600s"


def test_database_manager_is_rejected_at_the_edge(manifests):
    rules = one(manifests, "HTTPRoute")["spec"]["rules"]
    blocked = [
        r for r in rules
        if any(m.get("path", {}).get("value", "").startswith("/web/database")
               for m in r.get("matches", []))
    ]
    assert blocked, "database manager path is not handled at the edge"
    # It must not reach Odoo at all.
    assert not blocked[0].get("backendRefs"), (
        "database manager requests must not be forwarded to Odoo"
    )


def test_database_manager_rule_precedes_the_catch_all(manifests):
    # Gateway API matches the most specific path first, but an explicit
    # ordering check guards against someone reordering the rules later.
    rules = one(manifests, "HTTPRoute")["spec"]["rules"]
    paths = [
        m.get("path", {}).get("value", "")
        for r in rules for m in r.get("matches", [])
    ]
    assert paths.index("/web/database") < paths.index("/")


def test_default_rule_routes_to_the_web_port(manifests):
    rules = one(manifests, "HTTPRoute")["spec"]["rules"]
    catch_all = [
        r for r in rules
        if any(m.get("path", {}).get("value") == "/" for m in r.get("matches", []))
    ]
    assert catch_all
    assert catch_all[0]["backendRefs"][0]["port"] == 8069


def test_route_targets_the_service_that_exists(manifests):
    # A backendRef naming a service that is not rendered produces a route
    # that resolves to nothing and returns 500 at the gateway.
    service_name = one(manifests, "Service", "-web")["metadata"]["name"]
    for rule in one(manifests, "HTTPRoute")["spec"]["rules"]:
        for backend in rule.get("backendRefs", []):
            assert backend["name"] == service_name


def test_tenant_route_attaches_to_the_tls_listener(manifests):
    # The HTTP listener exists only to redirect. A route bound to it would
    # serve the tenant in plaintext, and browsers strip navigator.clipboard,
    # service workers and other APIs on an insecure origin.
    parent = one(manifests, "HTTPRoute")["spec"]["parentRefs"][0]
    assert parent.get("sectionName") == "https"
