from conftest import by_kind, one


def test_namespace_enforces_restricted_pod_security(manifests):
    namespace = one(manifests, "Namespace")
    labels = namespace["metadata"]["labels"]
    assert labels["pod-security.kubernetes.io/enforce"] == "restricted"
    assert labels["pod-security.kubernetes.io/enforce-version"]


def test_default_deny_policy_exists_for_both_directions(manifests):
    policies = by_kind(manifests, "NetworkPolicy")
    deny = [p for p in policies if p["metadata"]["name"].endswith("default-deny")]
    assert len(deny) == 1, "expected exactly one default-deny policy"
    spec = deny[0]["spec"]
    assert spec["podSelector"] == {}, "default-deny must select every pod"
    assert set(spec["policyTypes"]) == {"Ingress", "Egress"}
    assert "ingress" not in spec and "egress" not in spec


def test_every_allow_policy_names_a_specific_peer(manifests):
    # A rule with an empty `from` or `to` allows everything, silently
    # defeating the default-deny it sits beside.
    for policy in by_kind(manifests, "NetworkPolicy"):
        if policy["metadata"]["name"].endswith("default-deny"):
            continue
        for rule in policy["spec"].get("ingress", []):
            assert rule.get("from"), f"{policy['metadata']['name']} allows all ingress"
        for rule in policy["spec"].get("egress", []):
            assert rule.get("to"), f"{policy['metadata']['name']} allows all egress"


def test_dns_egress_is_allowed(manifests):
    # Without an explicit DNS allow, default-deny egress breaks every lookup
    # and the failure presents as an application bug.
    assert any("dns" in p["metadata"]["name"] for p in by_kind(manifests, "NetworkPolicy"))


def test_no_policy_selects_pods_in_another_namespace(manifests):
    for policy in by_kind(manifests, "NetworkPolicy"):
        assert policy["metadata"]["namespace"] == "acme"


def test_resource_quota_is_declared(manifests):
    hard = one(manifests, "ResourceQuota")["spec"]["hard"]
    assert "requests.cpu" in hard and "limits.memory" in hard


def test_limitrange_sets_container_defaults(manifests):
    limits = one(manifests, "LimitRange")
    assert any(item["type"] == "Container" for item in limits["spec"]["limits"])


def test_no_policy_allows_the_whole_internet(manifests):
    # A 0.0.0.0/0 egress rule passes a naive "names a peer" check while
    # letting a compromised pod reach any host on that port.
    for policy in by_kind(manifests, "NetworkPolicy"):
        for direction in ("ingress", "egress"):
            for rule in policy["spec"].get(direction, []) or []:
                peers = rule.get("from" if direction == "ingress" else "to") or []
                for peer in peers:
                    cidr = peer.get("ipBlock", {}).get("cidr")
                    assert cidr != "0.0.0.0/0", (
                        f"{policy['metadata']['name']} allows all of {direction} to 0.0.0.0/0"
                    )
