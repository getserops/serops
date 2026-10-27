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

{{/* Effective DATABASE_URL.
     devServices.postgresql wins when enabled, so turning on the bundled
     database actually connects the app to it. Previously enabling it
     deployed a Postgres and changed nothing else, and the backend crashed
     on a missing database-url secret key. */}}
{{- define "serops.databaseUrl" -}}
{{- if .Values.devServices.postgresql.enabled -}}
{{- printf "postgres://%s:%s@%s:5432/%s"
      .Values.devServices.postgresql.user
      .Values.devServices.postgresql.password
      (include "serops.devPostgresHost" .)
      .Values.devServices.postgresql.database -}}
{{- else -}}
{{- .Values.database.url -}}
{{- end -}}
{{- end -}}

{{/* Effective CELERY_BROKER_URL — same precedence as the database. */}}
{{- define "serops.brokerUrl" -}}
{{- if .Values.devServices.redis.enabled -}}
{{- printf "redis://%s:6379/0" (include "serops.devRedisHost" .) -}}
{{- else -}}
{{- .Values.broker.url -}}
{{- end -}}
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
