# Odoo on Kubernetes

A production-shaped, multi-tenant Odoo deployment on Kubernetes: one Helm
chart, one namespace per customer, hardened by default, backed up in two
places, and instrumented to catch the failures where Odoo keeps serving
traffic while something important has quietly stopped.

The reasoning — every decision, its alternatives, the numbers at 500 tenants,
and an honest list of what is missing — is in **[DESIGN.md](DESIGN.md)**.

## Prerequisites

`docker`, `kind`, `kubectl`, `helm` (v3 or v4), `python3` with `pytest` and
`PyYAML` (`pip install -r requirements-dev.txt`), and `bats` for the shell
tests.

## Quickstart

```bash
make cluster              # three-node kind cluster named odoo
make platform             # operators, gateway, monitoring, MinIO, ArgoCD, External Secrets
```

## Provisioning a tenant

A tenant is a values file in `tenants/`. `make platform` installs ArgoCD, whose
committed `ApplicationSet` creates one `Application` per file there, so adding a
customer is a commit:

```bash
cp tenants/beta.yaml tenants/newco.yaml   # edit name, hostname, backup paths
make seed TENANT=newco                    # write its credentials to the store
git add tenants/newco.yaml && git commit -m "tenant: newco" && git push
kubectl -n argocd get applications -w     # watch it sync
```

Credentials are **declared, not generated**: the chart renders an
`ExternalSecret` per credential, and External Secrets materialises the Secret
into the tenant namespace from the store. That is why seeding happens before the
commit, and why no tenant namespace has to exist yet — the store needs the
values, and ArgoCD creates the namespace along with everything else.

Locally the store is a Kubernetes namespace (`odoo-credentials`) that `make seed`
fills, standing in for Vault. In production the `ClusterSecretStore` points at
Vault and `make seed` is not used at all; the chart and the tenant's values file
are unchanged either way. `make seed` is idempotent: it never overwrites a
credential that exists, so it will not rotate anything.

ArgoCD is at `kubectl -n argocd port-forward svc/argocd-server 8080:443`, logged
in as `admin` with the password from the `argocd-initial-admin-secret`.

Helm is still used, but only to **render** the chart: ArgoCD renders it that way,
and the tests and CI use `helm template` and `helm lint`. Nothing installs with
Helm — one provisioner means one owner for every object.



## Reaching the running stack

The Gateway is a NodePort mapped to the host by the kind config, so add both
hosts to `/etc/hosts` first:

```
127.0.0.1 acme.odoo.local grafana.odoo.local
```

| What | Where |
|---|---|
| Odoo | <https://acme.odoo.local:8443> |
| Grafana | <https://grafana.odoo.local:8443> |
| Prometheus, Alertmanager | In-cluster only; reached through the API-server proxy |

TLS is self-signed here, so expect a certificate warning (or `curl -k`).

Credentials are generated per install and never committed. To read one:

```bash
# Grafana
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d

# A tenant's Odoo admin password (key: admin_passwd)
kubectl -n acme get secret acme-odoo-admin \
  -o jsonpath='{.data.admin_passwd}' | base64 -d
```

## Verifying it

```bash
make test    # chart unit tests and shell tests; no cluster needed
make e2e     # asserts the live cluster: targets up, canary, backups, alerts,
             # Grafana's datasource, and tenant isolation
helm test acme -n acme   # in-cluster: connectivity, database manager closed,
                         # default admin credential rejected
```

`make test` is the fast loop and the one CI runs. `make e2e` is the honest
one: it fails if a scrape target is down, if the login canary cannot
authenticate, if the last base backup is older than 26 hours, if the restore
drill has not recorded a success, if an expected alert rule is missing, if
Grafana has lost its default Prometheus datasource, or if a tenant's web pod
can reach the monitoring namespace or another tenant's database.

## What is in here

| Path | What it is |
|---|---|
| `charts/odoo-tenant/` | The one chart: web, cron, CloudNativePG cluster, pooler, canary, sql_exporter, backups, restore drill, network policies, alerts |
| `tenants/` | One values file per customer; credentials live in Secrets, not here |
| `platform/` | Cluster-wide: Gateway, monitoring stack and its policies, MinIO, ArgoCD, the External Secrets store |
| `cluster/kind.yaml` | The development cluster definition |
| `images/canary/` | Synthetic Odoo probe: JSON-RPC login plus a record read |
| `scripts/` | Platform install, credential seeding, filestore backup, restore drill |
| `tests/` | Chart unit tests, shell tests, and `tests/integration/` for the live cluster |
| `DESIGN.md` | The reasoning, the trade-offs, and the limits |

## Operations

**Tenants.** Add `tenants/<name>.yaml`, run `make seed TENANT=<name>` to put its
credentials in the store, and push. ArgoCD creates the namespace and everything
in it; External Secrets materialises the four credentials into that namespace.

**Backups.** CloudNativePG archives WAL continuously and takes scheduled base
backups to MinIO; a restic `CronJob` snapshots the filestore. Both are
required — a database-only restore returns an Odoo whose attachments are all
broken.

**The restore drill.** A scheduled `CronJob` restores the latest backup into a
throwaway cluster, asserts against the restored data, records
`odoo_restore_drill_success`, and deletes the cluster. Backups that have not
worked for months become an alert instead of a discovery during an incident.

**Alerts.** The silent-failure rules live in the chart, so a new tenant is
monitored the moment its namespace exists: stale backups, stalled WAL
archiving, a failing or stale restore drill, a failing canary, a stalled
`ir_cron`, mail queuing silently, filestore drift, and lock contention.

**Dashboards.** Grafana provisions three from ConfigMaps: an overview, backups
and recovery, and tenant health.

## Limitations

The gaps are listed in
[DESIGN.md](DESIGN.md#limits-and-what-i-would-do-next) rather than hidden:
Loki is specified but not deployed, images are pinned by tag rather than
digest, and TLS is self-signed.
