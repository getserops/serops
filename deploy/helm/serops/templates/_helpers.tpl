{{/* Chart-name helper — respects nameOverride. */}}
{{- define "serops.name" -}}
{{- default .Chart.Name .Values.global.nameOverride | trunc 63 | trimSuffix "-" -}}
{{- end -}}

{{/* Fully-qualified name (release + chart).
     Collapses when the release is already named after the chart, so
     `helm install serops ./serops` yields serops-backend rather than
     serops-serops-backend. This is the standard helm create idiom. */}}
{{- define "serops.fullname" -}}
{{- if .Values.global.fullnameOverride -}}
{{- .Values.global.fullnameOverride | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- $name := default .Chart.Name .Values.global.nameOverride -}}
{{- if contains $name .Release.Name -}}
{{- .Release.Name | trunc 63 | trimSuffix "-" -}}
{{- else -}}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Names of the optional bundled dev services. */}}
{{- define "serops.devPostgresHost" -}}
{{ printf "%s-postgres" (include "serops.fullname" .) }}
{{- end -}}
{{- define "serops.devRedisHost" -}}
{{ printf "%s-redis" (include "serops.fullname" .) }}
{{- end -}}

{{/* The ServiceAccount the pods run as. */}}
{{- define "serops.serviceAccountName" -}}
{{- if .Values.serviceAccount.create -}}
{{- default (include "serops.fullname" .) .Values.serviceAccount.name -}}
{{- else -}}
{{- default "default" .Values.serviceAccount.name -}}
{{- end -}}
{{- end -}}

{{/* Password of a bundled dev service. The value from values.yaml when set;
     otherwise the one already stored in the release's Secret (so upgrades
     keep it), or a fresh random one on first install. Call with
     (dict "root" $ "value" <values password> "key" <secret key>). Call it
     ONCE per render (secrets.yaml does) and let the pods read the Secret:
     a second call on a first install would draw a different random. */}}
{{- define "serops.devPassword" -}}
{{- if .value -}}
{{- .value -}}
{{- else -}}
{{- $existing := lookup "v1" "Secret" .root.Release.Namespace (printf "%s-secrets" (include "serops.fullname" .root)) -}}
{{- if and $existing (hasKey ($existing.data | default dict) .key) -}}
{{- index $existing.data .key | b64dec -}}
{{- else -}}
{{- randAlphaNum 32 -}}
{{- end -}}
{{- end -}}
{{- end -}}

{{/* Effective DATABASE_URL.
     devServices.postgresql wins when enabled, so turning on the bundled
     database actually connects the app to it. Previously enabling it
     deployed a Postgres and changed nothing else, and the backend crashed
     on a missing database-url secret key. Call with
     (dict "root" $ "password" <dev password>). */}}
{{- define "serops.databaseUrl" -}}
{{- if .root.Values.devServices.postgresql.enabled -}}
{{- printf "postgres://%s:%s@%s:5432/%s"
      .root.Values.devServices.postgresql.user
      .password
      (include "serops.devPostgresHost" .root)
      .root.Values.devServices.postgresql.database -}}
{{- else -}}
{{- .root.Values.database.url -}}
{{- end -}}
{{- end -}}

{{/* Effective CELERY_BROKER_URL — same precedence as the database. The
     bundled Redis requires a password (requirepass). */}}
{{- define "serops.brokerUrl" -}}
{{- if .root.Values.devServices.redis.enabled -}}
{{- printf "redis://:%s@%s:6379/0" .password (include "serops.devRedisHost" .root) -}}
{{- else -}}
{{- .root.Values.broker.url -}}
{{- end -}}
{{- end -}}

{{/* Egress rules shared by the backend, Celery and the migration job: DNS,
     the bundled dev services, then networkPolicy.egress (or everything,
     when that list is empty). */}}
{{- define "serops.backendEgress" -}}
{{- $ctx := dict "Chart" .Chart "Release" .Release "Values" .Values -}}
- to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: {{ .Values.networkPolicy.dnsNamespace }}
  ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
{{- if .Values.devServices.postgresql.enabled }}
- to:
    - podSelector:
        matchLabels:
          {{- include "serops.selectorLabels" (merge (dict "component" "dev-postgres") $ctx) | nindent 10 }}
  ports:
    - port: 5432
      protocol: TCP
{{- end }}
{{- if .Values.devServices.redis.enabled }}
- to:
    - podSelector:
        matchLabels:
          {{- include "serops.selectorLabels" (merge (dict "component" "dev-redis") $ctx) | nindent 10 }}
  ports:
    - port: 6379
      protocol: TCP
{{- end }}
{{- if .Values.networkPolicy.egress }}
{{ toYaml .Values.networkPolicy.egress }}
{{- else }}
- {}
{{- end }}
{{- end -}}

{{/* Common labels stamped on every resource. */}}
{{- define "serops.labels" -}}
helm.sh/chart: {{ .Chart.Name }}-{{ .Chart.Version | replace "+" "_" }}
app.kubernetes.io/name: {{ include "serops.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end -}}

{{/* Selector labels for a component (backend, frontend, worker, beat). */}}
{{- define "serops.selectorLabels" -}}
app.kubernetes.io/name: {{ include "serops.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{/* Image reference — appVersion fallback for tag. */}}
{{- define "serops.image" -}}
{{- $repo := .repository -}}
{{- $tag := default .root.Chart.AppVersion .tag -}}
{{ printf "%s:%s" $repo $tag }}
{{- end -}}

{{/*
Queues the single worker Deployment consumes: whatever celeryWorker.queues
lists, plus every queue the backend routes tasks to (api/celery.py). The
chart used to default to "high_priority,celery" while analyze_batch goes to
"background" and the scheduler fan-out to "normal", so on a Helm install no
batch was ever scheduled or analysed. Merging here also heals releases
upgraded with --reuse-values, which keep the old value.
*/}}
{{- define "serops.workerQueues" -}}
{{- $required := list "celery" "high_priority" "normal" "background" -}}
{{- $configured := splitList "," (.Values.celeryWorker.queues | default "" | nospace) | compact -}}
{{- concat $configured $required | uniq | join "," -}}
{{- end -}}



{{/* Pod-level security and scratch volumes for pods running the backend
     image (backend, Celery worker and beat, migrations). The root
     filesystem is read-only, so /tmp (gunicorn heartbeats, beat schedule)
     and /app/logs get an emptyDir each. */}}
{{- define "serops.backendPodSecurity" -}}
securityContext:
  {{- toYaml .Values.podSecurityContext | nindent 2 }}
volumes:
  - name: tmp
    emptyDir: {}
  - name: logs
    emptyDir: {}
{{- end -}}

{{/* Container-level counterpart of serops.backendPodSecurity. */}}
{{- define "serops.backendContainerSecurity" -}}
securityContext:
  {{- toYaml .Values.containerSecurityContext | nindent 2 }}
volumeMounts:
  - name: tmp
    mountPath: /tmp
  - name: logs
    mountPath: /app/logs
{{- end -}}

{{/* Restricted container settings for the bundled dev services (their
     entrypoints write outside a volume, so the root filesystem stays
     writable; the data lives in an emptyDir anyway). */}}
{{- define "serops.devContainerSecurity" -}}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: ["ALL"]
{{- end -}}

{{/*
Scheduling for a component's pods: nodeSelector, tolerations, affinity and
topologySpreadConstraints from its values. A replicated component (spread:
true) gets a soft one-per-node spread unless it sets its own constraints:
two replicas on the same node were lost together when that node went down
(found on a 2-node AKS cluster). Soft (ScheduleAnyway) so a single-node
cluster still schedules them. Call with (dict "root" $ "values" .Values.x
"component" "x" "spread" true).
*/}}
{{- define "serops.scheduling" -}}
{{- $v := .values -}}
{{- with $v.nodeSelector }}
nodeSelector:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $v.tolerations }}
tolerations:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- with $v.affinity }}
affinity:
  {{- toYaml . | nindent 2 }}
{{- end }}
{{- if $v.topologySpreadConstraints }}
topologySpreadConstraints:
  {{- toYaml $v.topologySpreadConstraints | nindent 2 }}
{{- else if and .spread (ne (toString $v.spreadAcrossNodes) "false") }}
topologySpreadConstraints:
  - maxSkew: 1
    topologyKey: kubernetes.io/hostname
    whenUnsatisfiable: ScheduleAnyway
    labelSelector:
      matchLabels:
        {{- include "serops.selectorLabels" (dict "Chart" .root.Chart "Release" .root.Release "Values" .root.Values "component" .component) | nindent 8 }}
{{- end }}
{{- end }}
