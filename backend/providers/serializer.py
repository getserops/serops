from rest_framework import serializers
from .models import GitlabProject, Pipeline, Job, Deployment, CodeChange

class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = GitlabProject
        fields = ['id', 'gitlab_url','username','name', 'project_id', 'access_token','webhook']
        # The stored token (encrypted at rest) must never be returned, even to
        # the owning org. Input-only, like the modern integration serializer.
        extra_kwargs = {'access_token': {'write_only': True}}
        ref_name = "GitlabProject"  # Add this line to distinguish it

class PipelineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Pipeline
        fields = ['id', 'project', 'pipeline_id','status','branch']

class JobSerializer(serializers.ModelSerializer):
    class Meta:
        model = Job
        fields = ['id', 'pipeline', 'name', 'job_id','logs','error_summary','status']


class JobListSerializer(serializers.ModelSerializer):
    """Compact job for list contexts — omits full log payload."""
    log_size = serializers.SerializerMethodField()

    class Meta:
        model = Job
        fields = ['id', 'job_id', 'name', 'status', 'log_size']

    def get_log_size(self, obj):
        return len(obj.logs or '')


class PipelineListSerializer(serializers.ModelSerializer):
    """Rich pipeline list serializer — surfaces the fields UIs need without a per-pipeline round-trip."""
    jobs = JobListSerializer(many=True, read_only=True)
    project_name = serializers.CharField(source='project.name', read_only=True, allow_null=True)

    class Meta:
        model = Pipeline
        fields = [
            'id', 'pipeline_id', 'external_project_id', 'project_name',
            'cicd_provider', 'status', 'branch', 'environment',
            'created_at', 'jobs',
        ]


class DeploymentListSerializer(serializers.ModelSerializer):
    """Runtime deployment events (providers.Deployment) — one row per (code_change → environment)."""
    commit_sha = serializers.CharField(source='code_change.commit_sha', read_only=True)
    commit_message = serializers.CharField(source='code_change.commit_message', read_only=True)
    pipeline_external_id = serializers.CharField(source='pipeline.pipeline_id', read_only=True, allow_null=True)
    pipeline_status = serializers.CharField(source='pipeline.status', read_only=True, allow_null=True)

    class Meta:
        model = Deployment
        fields = [
            'id', 'environment', 'status', 'deployed_at',
            'commit_sha', 'commit_message',
            'pipeline', 'pipeline_external_id', 'pipeline_status',
        ]