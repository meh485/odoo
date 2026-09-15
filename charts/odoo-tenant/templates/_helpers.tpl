{{/* Validate the tenant name early: an invalid DNS label produces objects the
     API server rejects, and a blank one would silently collide across tenants. */}}
{{- define "odoo.tenant" -}}
{{- $name := .Values.tenant.name | default .Release.Name -}}
{{- if not (regexMatch "^[a-z][a-z0-9-]{1,30}$" $name) -}}
{{- fail (printf "tenant name %q is invalid: must match ^[a-z][a-z0-9-]{1,30}$" $name) -}}
{{- end -}}
{{- $name -}}
{{- end -}}

{{- define "odoo.labels" -}}
app.kubernetes.io/name: odoo
app.kubernetes.io/instance: {{ include "odoo.tenant" . }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end -}}

{{- define "odoo.selectorLabels" -}}
app.kubernetes.io/name: odoo
app.kubernetes.io/instance: {{ include "odoo.tenant" . }}
{{- end -}}

{{/* Shared pod-level hardening. Applied to every workload in the chart. */}}
{{- define "odoo.podSecurityContext" -}}
runAsNonRoot: true
runAsUser: 101
runAsGroup: 101
fsGroup: 101
seccompProfile:
  type: RuntimeDefault
{{- end -}}

{{- define "odoo.containerSecurityContext" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end -}}
