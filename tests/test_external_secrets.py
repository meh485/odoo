"""The chart declares its credentials rather than generating them, so the four
Secrets it references are materialised by the operator.

Two invariants matter most. The Secret names do not change: consumers still mount
{tenant}-odoo-admin and friends, only who produces them changed. And each tenant
reads through its own store, whose reader may reach exactly one Secret in the
shared credentials namespace -- a single reader there would need `get` across
every tenant, so one mistake would expose every customer at once.
"""
from conftest import by_kind, helm_template, one

STORED = {"credentials": {"externalSecrets": {"enabled": True}}}
BACKUP = {
    **STORED,
    "backup": {
        "enabled": True,
        "destinationPath": "s3://odoo-backups/acme",
        "endpointURL": "http://minio:9000",
        "filestore": {"enabled": True, "repository": "s3:http://minio/odoo-backups/acme"},
    },
}
EXTERNAL_STORE = {
    "credentials": {
        "externalSecrets": {
            "enabled": True,
            "store": "vault-backend",
            "storeKind": "ClusterSecretStore",
            "reader": {"enabled": False},
        }
    }
}


def external_secrets(manifests) -> dict:
    return {es["metadata"]["name"]: es for es in by_kind(manifests, "ExternalSecret")}


def reader_role(manifests) -> dict:
    return one(manifests, "Role", "credential-reader")


def test_no_credentials_objects_unless_enabled(manifests):
    assert not by_kind(manifests, "ExternalSecret")
    assert not by_kind(manifests, "SecretStore")
    readers = [
        m["metadata"]["name"]
        for kind in ("Role", "RoleBinding", "ServiceAccount")
        for m in by_kind(manifests, kind)
        if m["metadata"]["name"].endswith("credential-reader")
    ]
    assert not readers, f"a reader is rendered while credentials are disabled: {readers}"


def test_every_credential_the_chart_references_is_declared():
    assert set(external_secrets(helm_template(BACKUP))) == {
        "acme-odoo-admin",
        "acme-canary",
        "acme-restic",
        "acme-backup-credentials",
    }


def test_each_tenant_reads_through_its_own_store():
    manifests = helm_template(BACKUP)
    assert one(manifests, "SecretStore", "acme-credentials")["metadata"]["namespace"] == "acme"
    for secret in external_secrets(manifests).values():
        assert secret["spec"]["secretStoreRef"] == {
            "name": "acme-credentials",
            "kind": "SecretStore",
        }
        assert {d["remoteRef"]["key"] for d in secret["spec"]["data"]} == {"acme"}


def test_the_store_reads_the_shared_credentials_namespace():
    provider = one(helm_template(BACKUP), "SecretStore", "acme-credentials")["spec"]["provider"]
    assert provider["kubernetes"]["remoteNamespace"] == "odoo-credentials"
    assert provider["kubernetes"]["auth"]["serviceAccount"]["name"] == "acme-credential-reader"


def test_the_store_omits_the_ca_namespace():
    # External Secrets rejects a namespaced store that sets it -- "CAProvider
    # .namespace must be empty with SecretStore" -- and reads the CA from the
    # store's own namespace instead. It looks like an omission, so it is pinned.
    provider = one(helm_template(BACKUP), "SecretStore", "acme-credentials")["spec"]["provider"]
    assert "namespace" not in provider["kubernetes"]["server"]["caProvider"]


def test_the_reader_can_reach_only_this_tenants_secret():
    role = reader_role(helm_template(BACKUP))
    assert role["metadata"]["namespace"] == "odoo-credentials"
    assert role["rules"] == [
        {
            "apiGroups": [""],
            "resources": ["secrets"],
            "verbs": ["get"],
            "resourceNames": ["acme"],
        }
    ]


def test_the_reader_is_bound_to_an_account_in_the_tenant_namespace():
    manifests = helm_template(BACKUP)
    binding = one(manifests, "RoleBinding", "credential-reader")
    assert binding["metadata"]["namespace"] == "odoo-credentials"
    assert binding["subjects"] == [
        {"kind": "ServiceAccount", "name": "acme-credential-reader", "namespace": "acme"}
    ]

    account = one(manifests, "ServiceAccount", "credential-reader")
    assert account["metadata"]["namespace"] == "acme"
    assert account["automountServiceAccountToken"] is False


def test_an_external_store_renders_no_reader_of_its_own():
    manifests = helm_template(EXTERNAL_STORE)
    assert not by_kind(manifests, "SecretStore")
    readers = [
        m["metadata"]["name"]
        for kind in ("Role", "RoleBinding", "ServiceAccount")
        for m in by_kind(manifests, kind)
        if m["metadata"]["name"].endswith("credential-reader")
    ]
    assert not readers, f"a Kubernetes reader is rendered for an external store: {readers}"
    for secret in external_secrets(manifests).values():
        assert secret["spec"]["secretStoreRef"] == {
            "name": "vault-backend",
            "kind": "ClusterSecretStore",
        }


def test_the_target_names_match_what_the_workloads_mount():
    manifests = helm_template(BACKUP)
    declared = {
        name: secret["spec"]["target"]["name"]
        for name, secret in external_secrets(manifests).items()
    }
    assert all(name == target for name, target in declared.items())

    pod = one(manifests, "Deployment", "-web")["spec"]["template"]["spec"]
    mounted = {
        source["secret"]["name"]
        for volume in pod["volumes"]
        if "projected" in volume
        for source in volume["projected"]["sources"]
    }
    assert {"acme-odoo-admin", "acme-canary"} <= mounted


def test_the_remote_key_can_be_overridden():
    values = {
        "credentials": {
            "externalSecrets": {
                **STORED["credentials"]["externalSecrets"],
                "remoteKey": "vault/acme",
            }
        }
    }
    manifests = helm_template(values)
    secret = external_secrets(manifests)["acme-canary"]
    assert {d["remoteRef"]["key"] for d in secret["spec"]["data"]} == {"vault/acme"}
    # The reader follows the key: it is scoped to whatever this tenant reads.
    assert reader_role(manifests)["rules"][0]["resourceNames"] == ["vault/acme"]
