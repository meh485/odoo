#!/usr/bin/env bash
# Install the platform operators and apply the platform-owned manifests.
# Idempotent: rerunning upgrades the operators and re-applies the manifests.
set -euo pipefail

CNPG_VERSION="1.25.0"
ENVOY_GATEWAY_VERSION="v1.9.1"
ENVOY_GATEWAY_CHART="oci://docker.io/envoyproxy/gateway-helm"
KUBE_PROMETHEUS_VERSION="91.4.0"
ARGOCD_VERSION="v3.5.3"

# CloudNativePG publishes an install manifest rather than a Helm chart. The
# image tag it deploys is what the cluster runs today.
kubectl apply --server-side -f \
  "https://raw.githubusercontent.com/cloudnative-pg/cloudnative-pg/release-1.25/releases/cnpg-${CNPG_VERSION}.yaml"

# Envoy Gateway is distributed as an OCI Helm chart.
helm upgrade --install eg "${ENVOY_GATEWAY_CHART}" \
  --version "${ENVOY_GATEWAY_VERSION}" \
  --namespace envoy-gateway-system --create-namespace

# The monitoring namespace is created here, with its Pod Security Standard
# labels in place, before the observability stack lands in it.
kubectl apply -f platform/monitoring/pushgateway.yaml

# Prometheus, Alertmanager and their operator. The operator's CRDs are what
# give the tenants' ServiceMonitors and alert rules meaning, so the rest of
# the platform is applied after this.
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts >/dev/null
helm repo update >/dev/null
helm upgrade --install kube-prometheus-stack prometheus-community/kube-prometheus-stack \
  --version "${KUBE_PROMETHEUS_VERSION}" \
  --namespace monitoring \
  -f platform/monitoring/kube-prometheus-stack-values.yaml

# ArgoCD, which provisions the tenants from git. It is installed here, before
# the platform manifests are applied at the end of this script, because the
# ApplicationSet and AppProject in platform/argocd are ArgoCD custom resources:
# applying them without these CRDs fails, and under `set -e` that aborts the
# whole install.
kubectl create namespace argocd --dry-run=client -o yaml | kubectl apply -f - >/dev/null
kubectl apply --server-side -n argocd \
  -f "https://raw.githubusercontent.com/argoproj/argo-cd/${ARGOCD_VERSION}/manifests/install.yaml"

# Platform manifests are applied, not templated: the gateway, the object store
# and the metrics sink are platform-owned and shared by every tenant.
kubectl apply -f platform/

# The object store needs a root credential that is deliberately not committed,
# mirroring how the gateway's TLS secret is created out of band. It is created
# once; tenant backup credentials are seeded from it by `make tenant`.
if ! kubectl get secret minio-credentials -n storage >/dev/null 2>&1; then
  kubectl create secret generic minio-credentials -n storage \
    --from-literal=ACCESS_KEY_ID="$(openssl rand -hex 12)" \
    --from-literal=ACCESS_SECRET_KEY="$(openssl rand -hex 24)"
fi

echo "waiting for the operators to become available"
kubectl wait --for=condition=Available --timeout=300s \
  deployment/cnpg-controller-manager -n cnpg-system
kubectl wait --for=condition=Available --timeout=300s \
  deployment/envoy-gateway -n envoy-gateway-system

echo "platform ready"