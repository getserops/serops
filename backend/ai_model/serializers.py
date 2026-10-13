from rest_framework import serializers

class LogMetadataSerializer(serializers.Serializer):
    client_id = serializers.CharField(required=False)
    request_id = serializers.CharField(required=False)
    error_type = serializers.CharField(required=False)
    method = serializers.CharField(required=False)
    path = serializers.CharField(required=False)
    latency_ms = serializers.IntegerField(required=False)
    headers = serializers.DictField(required=False)
    upstream_service = serializers.CharField(required=False)

class LogEntrySerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    level = serializers.CharField()
    message = serializers.CharField()
    metadata = LogMetadataSerializer(required=False)

class ServiceMetricsSerializer(serializers.Serializer):
    request_rate = serializers.FloatField(required=False)
    error_rate = serializers.FloatField(required=False)
    p99_latency = serializers.FloatField(required=False)
    active_sessions = serializers.IntegerField(required=False)
    cache_hit_rate = serializers.FloatField(required=False)
    db_query_latency = serializers.FloatField(required=False)

class ServiceDataSerializer(serializers.Serializer):
    logs = serializers.DictField(child=serializers.ListField(child=LogEntrySerializer()))
    metrics = ServiceMetricsSerializer(required=False)

class InfrastructureMetricsSerializer(serializers.Serializer):
    kubernetes = serializers.DictField()
    database = serializers.DictField()

class BatchLogsSerializer(serializers.Serializer):
    batch_id = serializers.CharField()
    timestamp = serializers.DateTimeField()
    environment = serializers.CharField()
    services = serializers.DictField(child=ServiceDataSerializer())
    infrastructure_metrics = InfrastructureMetricsSerializer()
    correlation_ids = serializers.DictField()


class ChatPromptSerializer(serializers.Serializer):
    message = serializers.CharField(required=True)
    context = serializers.ListField(child=serializers.CharField(), required=False)


class ChatRequestSerializer(serializers.Serializer):
    type = serializers.CharField(required=True)
    prompt = serializers.DictField()
    ai_model = serializers.CharField(required=False, default='pods')
    chat_id = serializers.UUIDField(required=False)
    batch_id = serializers.CharField(required=False, allow_null=True)

class BatchAnalysisRequestSerializer(serializers.Serializer):
    batch_id = serializers.CharField(help_text="Unique identifier for the batch to analyze")