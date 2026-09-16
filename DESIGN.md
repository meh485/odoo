# Production-ready Odoo on Kubernetes

How this repository runs Odoo for many customers on one Kubernetes cluster,
why each choice was made, and what has been proven to work on a running
cluster rather than only argued for.

The starting point is the brief: much. Consulting is moving roughly 50 Odoo
customers off managed hosting onto self-operated infrastructure and expects to
reach 500+. The deliverable is this repository plus the reasoning below.

## Architecture at a glance

```
tenants/<name>.yaml  ->  charts/odoo-tenant (Helm)  ->  one namespace per tenant
                             |                            acme-web, acme-cron
                             |                            acme-db (CloudNativePG)
                             |                            acme-pooler, canary,
                             |                            sql-exporter, backups
platform/
  gateway/     Envoy Gateway, GatewayClass, Gateway, HTTPRoute plumbing
  monitoring/  kube-prometheus-stack values, ServiceMonitors, alerts,
               NetworkPolicies, Grafana dashboards, pushgateway
  storage/     MinIO, the S3 endpoint CloudNativePG and restic write to
  argocd/      ApplicationSet: one Application per directory in tenants/
images/canary/ Synthetic Odoo probe, built locally and loaded into kind
```

A tenant is a values file. Adding a customer is a commit: the ApplicationSet
renders an `Application` per file under `tenants/`, and ArgoCD is the only thing
that installs a tenant. Helm still renders the chart — ArgoCD renders it that
way, and the tests and CI use `helm template` — but nothing installs with Helm,
so every object in a tenant namespace has exactly one owner. That matters: the
two bugs that cost the most time in this project were both one object with two
owners.

Nothing above shares a database, a namespace, or a network policy with another
tenant.

## Platform decisions

**Kubernetes on kind for development.** One platform, so configuration
transfers. kind runs vanilla upstream Kubernetes, starts in seconds, and is
what CloudNativePG and Envoy Gateway document their own installation against.
k3d was rejected: k3s substitutes the service load balancer, the default
ingress, and the storage backend, which reintroduces exactly the
development/production gap this decision closes.

Two local-only accommodations live in `platform/` and never touch the chart:
kind has no cloud load balancer, so the Gateway is a NodePort matching the
cluster's port mapping, and Envoy is pinned to the node holding that mapping
because the generated Service uses `externalTrafficPolicy: Local`. In a real
cluster both disappear into the provider's LoadBalancer.

**A namespace per tenant.** Namespaces give a natural boundary for RBAC,
quotas, and network policy, and make teardown a single comprehensible
operation. A shared namespace with label separation was rejected because it
couples blast radius and makes per-tenant network policy awkward to express.

**Odoo 19.0.** The current stable release; starting one version behind means
inheriting an upgrade before shipping. 19.0 also reads `PG*` environment
variables natively, which 17 and 18 do not — in those versions the upstream
entrypoint passes credentials as command-line arguments, where they show up in
the container's process list.

**CloudNativePG for PostgreSQL.** An operator rather than a StatefulSet:
`kind: Cluster` declares instances, storage, and backup destination, and the
operator runs replication, failover, continuous WAL archiving, point-in-time
recovery, and rolling minor upgrades. `kind: ScheduledBackup` replaces the
backup script and its cron entirely, and `kind: Pooler` runs PgBouncer. Pooling
is `session`, never `transaction`: Odoo relies on prepared statements and
session state, and transaction pooling breaks them intermittently rather than
cleanly.

The cost is real and stated: an operator is another dependency to understand
and upgrade, and when it misbehaves the debugging target is a controller rather
than a script. It is still the right trade — it removes the largest block of
bespoke code available — but it is why the restore drill exists, to verify what
the operator produces rather than trusting it.

**Envoy Gateway with Gateway API.** Gateway API is the Ingress successor and
needs an implementation behind it. ingress-nginx entered retirement in March
2026, so building on it would be building on a dead project. Gateway API also
expresses the ownership split that matters at 500 customers: the `Gateway`
belongs to the platform team, each tenant's `HTTPRoute` to the tenant.

**Helm chart plus ArgoCD ApplicationSet.** One chart, one values file per tenant
in git, one `Application` per tenant from a git files generator, so provisioning
is a commit and drift is continuously reconciled. ArgoCD runs on the demo
cluster too, installed by `scripts/platform-install.sh`, and provisions every
tenant except `acme` — which predates it here and is still installed by Helm,
because two owners for one set of objects is the conflict this repository has
already been bitten by once.

### Bootstrapping a tenant in order

A tenant cannot be applied all at once: the schema-init job needs the database,
and the web deployment needs the schema. Helm expresses that ordering with
post-install hook weights. ArgoCD expresses it with sync-waves, and the two
cannot be the same object: ArgoCD maps `helm.sh/hook: post-install` to a PostSync
hook, and PostSync runs only after every other resource is healthy — which the
web deployment never is until the init job has run. The sync waits on the
resource that waits on the job.

So the two one-time jobs switch annotation sets on an `argocd.enabled` value
that only the ApplicationSet sets. Helm keeps its hooks and weights; ArgoCD gets
Sync hooks ordered by wave:

| Wave | Resources |
|---|---|
| 0 | namespace, configmaps, network policies, services, quota |
| 1 | CloudNativePG `Cluster` |
| 2 | `Pooler` |
| 3 | filestore PVC and the schema-init job |
| 4 | the users job, which sets the admin and canary passwords |
| 5 | web, cron, canary, sql_exporter |

The PVC sits in wave 3 with its first consumer: the storage class binds on first
consumer, so the claim is Pending — and therefore not healthy to ArgoCD — until a
pod mounts it.

ArgoCD also has to be told how to assess CloudNativePG's resources
(`platform/argocd/health-checks.yaml`). Without a health check it reports no
health for a `Cluster` or a `Pooler` and then waits for them to become healthy
anyway, so that wave never completes.

This is the one place the chart renders differently per platform, and it is the
minimum such difference: everything else is identical under `helm template` and
under ArgoCD, and a test asserts the wave ordering so a reordered bootstrap
fails the suite rather than the demo.

## Security hardening

Every tenant namespace is labelled for the `restricted` Pod Security Standard,
so the following are enforced by the API server rather than trusted:

- `runAsNonRoot: true` with an explicit `runAsUser`/`runAsGroup`
- `readOnlyRootFilesystem: true`, with an `emptyDir` where a process needs one
- `allowPrivilegeEscalation: false`, `capabilities.drop: [ALL]`
- `seccompProfile: RuntimeDefault`
- `automountServiceAccountToken: false` on every workload that does not call the
  API server

**NetworkPolicy default-deny** on ingress and egress in every tenant namespace,
with explicit allows for the paths that exist: Gateway → Odoo, Odoo → the
pooler, the pooler and the restore drill → Postgres, Prometheus → metrics
ports, and DNS. The monitoring namespace has its own default-deny and its own
explicit allows. This is enforced by the cluster rather than by network
topology, which is what the earlier Docker Compose design relied on.

**Secrets as files, never environment variables.** The Odoo config template
deliberately carries no password: the entrypoint merges the database credential
from a mounted secret file at startup, so it reaches neither the ConfigMap, the
pod environment, nor the process list. The canary mounts only its own
single-purpose credential, not the projected bundle the Odoo pods mount —
a compromised probe should not hold the admin password.

**Odoo's database manager is closed.** `list_db = False` and a tenant-pinned
`dbfilter` (`^<tenant>$`). Verified rather than assumed: the manager page still
renders, because `list_db = False` does not remove the page, but the operation
the page exists for is denied. `helm test` posts to `/web/database/list` on the
web Service, bypassing the Gateway, and asserts the response contains
`AccessDenied`. A database list that succeeded there would be unauthenticated
enumeration of every database on the instance.

**No default credentials.** Initialising an Odoo database from the CLI creates
an `admin` account whose password is literally `admin`, and a freshly
provisioned tenant would be reachable through the Gateway with that guessable
credential. A post-install hook Job therefore sets the admin password from a
mounted secret and creates the canary user. A `helm test` asserts that
authenticating as `admin` with the password `admin` fails, which turns the
guarantee into something the pipeline checks rather than something a runbook
claims.

**Almost nothing has an identity.** Only the restore drill has a
ServiceAccount, because it is the only workload that calls the API server: it is
the only pod with `automountServiceAccountToken: true`, and its Role is scoped
to this namespace, to `clusters` in `postgresql.cnpg.io`, and to reading exactly
one named Secret. Every other workload runs with
`automountServiceAccountToken: false` and has no token to steal. No wildcard
verbs and no cluster-scoped grants appear anywhere in the tenant.

**ResourceQuota and LimitRange per namespace**, so one tenant cannot starve a
node, and every workload declares requests and limits.

What is *not* hardened yet is listed under limits below — digest pinning,
Trivy, and gitleaks are specified in the brief but not wired into CI here.

## Data persistence and backup

Two independent stores must both be captured. A database-only backup restores
an Odoo whose every attachment is broken — a failure that surfaces weeks later
when somebody opens an old invoice.

- **Database.** CloudNativePG continuous WAL archiving plus scheduled base
  backups to S3-compatible object storage (MinIO in `platform/storage/`, real
  object storage in production), which together allow PITR to any second inside
  the retention window. `ScheduledBackup` owns the schedule.
- **Filestore.** Odoo's `/var/lib/odoo` on a PersistentVolumeClaim, snapshotted
  by a restic `CronJob` into the same bucket. Restic is used rather than volume
  snapshots because snapshots are a storage-provider feature and the backup
  should not depend on where the cluster happens to run.
- **Credentials.** The tenant values files contain no keys, and the chart
  generates none: it *declares* an `ExternalSecret` per credential and the
  operator materialises the Secret into the tenant namespace. Locally the store
  is a Kubernetes namespace seeded by `make seed`, standing in for Vault; in
  production the `ClusterSecretStore` points at Vault and the seeding script is
  not used. Because the ExternalSecret lives in the tenant namespace it is
  applied in the same sync as the namespace itself, which is what removes the
  ordering problem entirely — no credential has to exist before the tenant does.

Backup age is exported by the operator
(`cnpg_collector_last_available_backup_timestamp`) and alerted on: a backup that
has silently stopped is the industry's most common and most expensive silent
failure.

### The restore drill

A scheduled `CronJob` creates a throwaway CloudNativePG `Cluster` with
`bootstrap.recovery` pointing at the latest backup, waits for it to become
ready, asserts that the restored database holds at least one row in `res_users`
and that no module in `ir_module_module` is stuck in a transitional state
(`to install`, `to upgrade`, `to remove` — `uninstallable` is a stable state
and is deliberately not counted), then deletes the cluster and pushes the
result to the pushgateway:

- `odoo_restore_drill_success` (1 or 0)
- `odoo_restore_drill_duration_seconds`
- `odoo_restore_drill_last_run_timestamp_seconds`

Alerts fire when the drill fails or when its result goes stale, so "the backups
have not worked for months" becomes a paging condition instead of a discovery
during an incident. An operator's backups deserve this verification exactly as
much as a hand-written script's, which is why the drill was kept when the rest
of the Compose-era shell was deleted.

## Silent failures

This is the core of the submission. Each row is a real Odoo production failure
in which the service keeps answering requests while something important has
stopped.

| Failure | Expression, per tenant | Alert | Severity |
|---|---|---|---|
| Backups stopped | `time() - cnpg_collector_last_available_backup_timestamp > 93600` | `OdooBackupStale` | critical |
| WAL archiving stalled | `cnpg_pg_stat_archiver_seconds_since_last_archival > 300` | `OdooWalArchivingStalled` | warning |
| WAL archiving failing | `increase(cnpg_pg_stat_archiver_failed_count[1h]) > 0` | `OdooWalArchiveFailing` | warning |
| Backups exist but will not restore | drill result, and the age of that result | `OdooRestoreDrillFailed`, `OdooRestoreDrillStale` | critical |
| Odoo answers HTTP but login is broken | `odoo_canary_success == 0`, and how long since the probe ran | `OdooCanaryFailed`, `OdooCanaryStale` | critical, warning |
| `ir_cron` stalls — invoices and mail stop, nothing errors | `odoo_cron_overdue_seconds > 7200` | `OdooCronStalled` | critical |
| Outbound mail queuing silently | `odoo_mail_outgoing_age_seconds > 1800` | `OdooMailQueueStalled` | warning |
| Mail queue growing without draining | `odoo_mail_queue_depth > 100` | `OdooMailBacklog` | warning |
| Filestore drifts from the database | `abs(filestore - (total - database)) > 10` | `OdooAttachmentDrift` | warning |
| Lock contention stalls transactions | `pg_blocked_query_age_seconds > 300` | `OdooLockContention` | warning |

Every rule carries a `for:` of five minutes to an hour, so a single bad scrape
does not page anyone, and every rule is scoped to one tenant, so one customer's
incident does not produce alerts for the other 499.

The Odoo-domain signals are exported by a per-tenant `sql_exporter` Deployment
whose collector definitions live in the chart, so a new tenant is monitored the
moment its namespace exists. Severity carries the split: five rules are critical
— a stale backup, a failed canary, a stalled `ir_cron`, and a failed or stale
restore drill — and the rest are warnings. Alertmanager runs with the chart's
default inhibition, so a critical alert suppresses its lower-severity equals in
the same namespace with the same alert name, which is what stops one incident
producing three notifications. No external receiver is configured: alerts are
read in the Alertmanager UI and in Prometheus, and the receiver is null on
purpose.

### Why the canary authenticates

The probe performs a real JSON-RPC login as a dedicated read-only user and then
reads a known record. An HTTP check on `/` or `/web/health` is not sufficient,
and that is an observation from this cluster rather than a general claim: on
this very cluster `/web/health` returned 200 while the database had no schema
and every real request failed with `KeyError: 'ir.http'`. Authenticating and
reading exercises the database, the session store, and the ORM in one probe.
JSON-RPC rather than the HTML form avoids CSRF handling.

The canary publishes `odoo_canary_success` immediately on startup with a value
of 0, because an absent series and a failing series look different to an alert,
and only one of those is what a new tenant should look like.

## Observability

Prometheus Operator CRDs throughout: a `ServiceMonitor` or `PodMonitor` per
workload, `PrometheusRule` for the alert set above, and Grafana dashboards
provisioned from ConfigMaps by the chart's sidecar. Targets are discovered from
labels rather than a list, so a new tenant is monitored the moment its
namespace exists — there is no target file to forget to update.

Three dashboards ship: an overview, **backups and recovery** (backup age,
WAL archive lag, restore-drill result and age, attachments split across the
database and filestore), and **tenant health** (scrape targets up, canary
result and durations, Postgres backends and replication lag, database size,
cache hit ratio, restart rate, and the silent-failure signals). Every query in
them was checked against live Prometheus before the panel was written, so no
panel is decorative. The tenant-health dashboard takes its tenant from a
template variable discovered from the canary targets rather than hardcoding a
name, so the same dashboard serves one customer or all of them.

Alertmanager runs in-cluster. No external receiver is configured here; in
production these routes to whatever pages the on-call engineer.

The monitoring stack is trimmed for the demo: node-exporter is off because it
needs host access that `restricted` forbids, Grafana's bundled dashboards are
off in favour of the tenant-focused ones, and the etcd, scheduler,
controller-manager and kube-proxy monitors are off because kubeadm binds those
endpoints to 127.0.0.1 and no policy or scrape config can reach them. Under a
managed control plane they would be enabled. kube-state-metrics is kept,
because the restart panel on the tenant-health dashboard reads it.

Nothing this stack scrapes is permanently red: `make e2e` asserts that no `up`
is zero anywhere, not merely that the tenants are up. That assertion earned its
place by catching twelve cluster-component targets that the monitoring
namespace's own network policies were silently blocking — which is precisely
the sort of noise that teaches an operator to ignore alerts.

## Scaling to 500 tenants

A tenant is a values file; the ApplicationSet renders one `Application` per
entry, from a git files generator, so a customer is a file and nothing else.
Per-tenant resource *requests*, in the production shape (two Odoo web replicas,
three Postgres instances, two poolers):

| Component | Requests each | Count | Total |
|---|---|---|---|
| Odoo web | 250m / 1Gi | 2 | 500m / 2Gi |
| Odoo cron | 100m / 512Mi | 1 | 100m / 512Mi |
| Postgres | 250m / 1Gi | 3 | 750m / 3Gi |
| Pooler | 100m / 256Mi | 2 | 200m / 512Mi |
| Canary | 10m / 64Mi | 1 | 10m / 64Mi |
| sql_exporter | 10m / 32Mi | 1 | 10m / 32Mi |
| **Per tenant** | | | **≈1.6 vCPU / ≈6.1Gi** |

The chart's local defaults are deliberately smaller — one Odoo replica, one
Postgres instance, one pooler — and `tenants/*.yaml` set them; the counts above
are the production shape, which is what the arithmetic needs to be about.

Multiplied by 500: **≈785 vCPU and ≈3.0 TiB of memory requests**. On
16 vCPU / 64 GiB nodes, holding back 30% for system and burst, that is about
**71 nodes** — call it a 75-node floor plus control plane, since the binding
constraint is memory as much as CPU. Limits are roughly twice requests, so a
cluster where every tenant bursts simultaneously needs about double the
capacity; the honest answer is that requests set the footprint and limits set
the headroom, and only one of those is a capacity plan.

The demo cluster is three kind nodes of 8 vCPU / 13.6 GiB each and runs the
full monitoring stack plus the `acme` tenant; per-tenant requests are what keep
that possible.

A namespace per tenant is right into the low thousands. Beyond that,
control-plane object count and the cost of NetworkPolicy evaluation start to
bite, and the answer becomes cluster-per-region or a virtual-cluster approach
rather than a bigger cluster.

## Trade-offs

- **Two operators to run.** CloudNativePG and Envoy Gateway are dependencies
  to understand and upgrade, and their failure modes are controller-shaped.
  Accepted because they delete the most bespoke code and because the restore
  drill independently verifies what the database operator produces.
- **The restore drill is custom code.** No operator provides "and prove the
  backup restores". It is the one piece of custom logic kept from the Compose
  work, and it is the piece most likely to prevent a real incident.
- **Gateway API is younger than Ingress**, with a smaller operational corpus.
  Accepted because the alternative is a retired controller.
- **Session pooling costs connections.** Odoo holds a session-level connection
  for the life of a worker; transaction pooling would multiplex better and
  break Odoo intermittently. Correctness wins.
- **kind is slower than Compose** for iteration, and a new engineer needs a
  cluster before running anything. Parity was judged worth that.

## Limits, and what I would do next

Everything below is a real gap, not a hypothetical:

- **Loki is specified but not deployed.** Log aggregation is the next
  component to add; the manifests are not committed because an unrun manifest
  is a claim rather than a capability.
- **Digest-pinned images, Trivy, and gitleaks are not in CI.** Images are
  pinned by tag today; `ci.yml` runs shellcheck, bats, `helm lint`, a full
  render, and the chart unit tests. Supply-chain scanning is the obvious next
  CI step.
- **No predictive disk alert.** The brief asks for projected time-to-full
  rather than a static threshold; today there is a volume-usage alert, not a
  `predict_linear` one.
- **Crash-loop detection is a dashboard, not an alert.**
  `kube_pod_container_status_restarts_total` is on the tenant-health dashboard
  but has no rule of its own yet.
- **Vault is still not run.** External Secrets runs locally and materialises
  every tenant credential, but its backend here is a Kubernetes namespace seeded
  by `make seed` rather than Vault. Swapping the store is a values change and not
  a chart change, which is the point of declaring the credentials instead of
  generating them.
- **TLS is self-signed.** The Gateway terminates HTTPS; cert-manager is not
  wired, so certificates are not automatically issued or renewed.
- **The restore drill proves the database, not the filestore.** It asserts that
  users came back and that no module is half-upgraded; it does not restore a
  sample of restic objects and compare them with the attachment rows. Given
  that this design argues at length that a database-only restore is broken, the
  drill should be asserting the other half, and that is the next thing to add.
- **The restore-drill Role could be narrower for `clusters`.** The Secret read
  is already limited with `resourceNames`; the cluster rule cannot be, because
  the scratch cluster's name is generated per run. At 500 tenants the drill
  schedules would also need staggering so that every tenant does not restore in
  the same hour.
- **No multi-region or active-active.** Single region with tested recovery, as
  the brief allows.
- **`acme` is not ArgoCD-managed yet.** It predates ArgoCD on this cluster and
  is still a Helm release. Adopting it is a deliberate act, because two owners
  for one set of objects is the conflict this repository has already been bitten
  by twice.
- **The integration suite does not see ArgoCD-provisioned tenants.** Its fixture
  intersects `tenants/*.yaml` with Helm releases, so a tenant created by ArgoCD
  is skipped rather than asserted. That is why the suite passed while `beta` was
  broken, and it has to be fixed before it can be trusted as a gate.
- **ArgoCD reads this repository with a deploy key** generated for the demo,
  read-only and revocable in one command. A real installation uses whatever
  credential the organisation already has.

## How to verify any of this

```bash
make cluster          # kind cluster
make platform         # operators, Gateway, monitoring, MinIO, ArgoCD, External Secrets
make seed TENANT=acme # credentials, into the store the operator reads
                      # then commit and push tenants/acme.yaml; ArgoCD syncs it
make test             # chart unit tests and shell tests, no cluster needed
make e2e              # asserts the live cluster
kubectl -n acme get cluster,podmonitor,servicemonitor,prometheusrule
```

`make e2e` is the honest one: it fails if a scrape target is down, if the canary
cannot log in, if the last base backup is older than 26 hours, if the restore
drill has not recorded a success, if an expected alert rule is missing, if
Grafana has lost its default Prometheus datasource, or if a tenant's own web pod
reaches the monitoring namespace or another tenant's database.

What has been demonstrated on the running cluster, not just asserted:

- **Alerting end to end.** Scaling `acme-web` to zero drove
  `odoo_canary_success` to 0; `OdooCanaryFailed` moved from pending to firing
  after exactly its 5-minute `for`, appeared in Alertmanager as active, and
  cleared when the deployment was scaled back. No alert was left firing.
- **Tenant isolation.** From `acme-web` itself, a TCP connection to
  `acme-pooler:5432` succeeds (the control) while connections to Prometheus in
  `monitoring` and to a second tenant's pooler time out.
- **The database manager is closed** and **the default admin credential does
  not work**, both asserted by `helm test` rather than by argument.
- **Backups and the restore drill** produce metrics that the dashboards read
  back, and the drill has recorded a success.
