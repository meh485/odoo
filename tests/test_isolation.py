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


def test_outbound_internet_is_denied_by_default(manifests):
    # A tenant that can reach arbitrary hosts by default turns any application
    # compromise into a data exfiltration path.
    names = {p["metadata"]["name"] for p in by_kind(manifests, "NetworkPolicy")}
    assert not any("egress-internet" in n for n in names)
    assert not any("egress-smtp" in n for n in names)


def test_enabling_internet_still_excludes_private_ranges_and_metadata():
    from conftest import helm_template
    manifests = helm_template({"network": {"egress": {"internet": {"enabled": True}}}})
    policy = [p for p in by_kind(manifests, "NetworkPolicy")
              if "egress-internet" in p["metadata"]["name"]][0]
    block = policy["spec"]["egress"][0]["to"][0]["ipBlock"]
    excluded = set(block["except"])
    # The metadata endpoint hands out node credentials; private ranges are the
    # rest of the cluster. "Internet" must not quietly mean either.
    assert "169.254.169.254/32" in excluded
    assert {"10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"} <= excluded


def test_smtp_egress_requires_an_explicit_destination():
    from conftest import helm_template
    try:
        helm_template({"network": {"egress": {"smtp": {"enabled": True}}}})
    except AssertionError as exc:
        assert "cidr" in str(exc).lower()
    else:
        raise AssertionError("expected SMTP egress without a CIDR to fail rendering")
