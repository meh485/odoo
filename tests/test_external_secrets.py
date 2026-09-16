"""The chart declares its credentials rather than generating them, so the four
Secrets it references are materialised by the operator.

The invariant that matters most here is the last one: the Secret names do not
change. Consumers still mount {tenant}-odoo-admin and friends; only who produces
them changed.
"""
from conftest import by_kind, helm_template, one

STORED = {"credentials": {"externalSecrets": {"enabled": True, "store": "tenant-credentials"}}}
BACKUP = {
    **STORED,
    "backup": {
        "enabled": True,
        "destinationPath": "s3://odoo-backups/acme",
        "endpointURL": "http://minio:9000",
        "filestore": {"enabled": True, "repository": "s3:http://minio/odoo-backups/acme"},
    },
}


def external_secrets(manifests) -> dict:
    return {es["metadata"]["name"]: es for es in by_kind(manifests, "ExternalSecret")}


def test_no_external_secrets_unless_enabled(manifests):
    assert not by_kind(manifests, "ExternalSecret")


def test_every_credential_the_chart_references_is_declared():
    assert set(external_secrets(helm_template(BACKUP))) == {
        "acme-odoo-admin",
        "acme-canary",
        "acme-restic",
        "acme-backup-credentials",
    }


def test_the_store_and_the_remote_key_are_used():
    for secret in external_secrets(helm_template(BACKUP)).values():
        assert secret["spec"]["secretStoreRef"] == {
            "name": "tenant-credentials",
            "kind": "ClusterSecretStore",
        }
        assert {d["remoteRef"]["key"] for d in secret["spec"]["data"]} == {"acme"}


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
    secret = external_secrets(helm_template(values))["acme-canary"]
    assert {d["remoteRef"]["key"] for d in secret["spec"]["data"]} == {"vault/acme"}
