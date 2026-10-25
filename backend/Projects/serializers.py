# backend/your_app/serializers.py
from rest_framework import serializers
from .models import (
    Project, ProjectService, ProjectEnvironment, SCMBinding, CICDBinding,
    ProjectDeployment,
)
from providers.serializer import ProjectSerializer as GitlabProjectSerializer
from providers.models import GitlabProject, ProviderIntegration
from providers.serializers import ProviderIntegrationListSerializer


class ProjectEnvironmentSerializer(serializers.ModelSerializer):
    """Serializer for project environments."""

    class Meta:
        model = ProjectEnvironment
        fields = [
            'id', 'name', 'display_name', 'branch_patterns',
            'tag_patterns', 'log_label_value', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']


class ProjectDeploymentSerializer(serializers.ModelSerializer):
    """Serializer for ProjectDeployment (Batch 52).

    A deployment = one instance of "where a project runs" — env × cluster
    × region × namespace. Read-only cluster metadata is surfaced flat so
    the frontend can render pills without a second round-trip. ``name``
    is user-editable; when omitted, ``suggest_name()`` auto-fills from
    the four dimensions on save.
    """

    cluster_name = serializers.CharField(source='cluster.name', read_only=True, allow_null=True)
    cluster_provider = serializers.CharField(
        source='cluster.get_provider_display', read_only=True, allow_null=True,
    )
    environment_name = serializers.CharField(
        source='environment.name', read_only=True, allow_null=True,
    )
    environment_display_name = serializers.CharField(
        source='environment.display_name', read_only=True, allow_null=True,
    )

    class Meta:
        model = ProjectDeployment
        fields = [
            'id', 'project', 'environment', 'environment_name', 'environment_display_name',
            'cluster', 'cluster_name', 'cluster_provider',
            'region', 'namespace', 'name', 'is_active',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        # Enforce namespace-requires-cluster at the serializer level so
        # we return a clean 400 rather than a raw IntegrityError from
        # the DB CheckConstraint. Same rule the model itself enforces.
        namespace = attrs.get('namespace', getattr(self.instance, 'namespace', '') or '')
        cluster = attrs.get('cluster', getattr(self.instance, 'cluster', None))
        if namespace and not cluster:
            raise serializers.ValidationError({
                'namespace': 'A namespace can only be set when a cluster is selected.',
            })
        # The environment must be the project's, and the cluster the
        # organisation's: ids of another organisation's rows are refused.
        project = attrs.get('project', getattr(self.instance, 'project', None))
        environment = attrs.get('environment', getattr(self.instance, 'environment', None))
        if environment is not None and project is not None and environment.project_id != project.id:
            raise serializers.ValidationError({'environment': 'Environment not found for this project.'})
        request = self.context.get('request')
        org_id = getattr(getattr(request, 'user', None), 'organisation_id', None)
        if cluster is not None and cluster.organisation_id != org_id:
            raise serializers.ValidationError({'cluster': 'Cluster not found for your organisation.'})
        return attrs

    def validate_project(self, value):
        # Tenant boundary: the target project must belong to the caller's
        # org. Prevents cross-org deployment creation via a crafted POST
        # (same defence pattern as SCM/CICDBinding create views).
        request = self.context.get('request')
        if request is not None and getattr(request.user, 'organisation_id', None):
            if value.organisation_id != request.user.organisation_id:
                raise serializers.ValidationError(
                    'Project does not belong to your organisation.'
                )
        return value


class ProjectSerializer(serializers.ModelSerializer):
    # Include environments in project response
    environments = ProjectEnvironmentSerializer(many=True, read_only=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)
    services = serializers.SerializerMethodField()

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'created_at', 'updated_at', 'environments', 'services']

    def get_services(self, obj):
        return ProjectServiceSerializer(obj.services.all(), many=True, context=self.context).data


class ProjectCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating a project with environments.
    Environments can be provided or defaults will be created.
    """
    environments = ProjectEnvironmentSerializer(many=True, required=False)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'organisation', 'environments']
    
    def create(self, validated_data):
        from .models import create_default_environments
        
        environments_data = validated_data.pop('environments', None)
        project = Project.objects.create(**validated_data)
        
        if environments_data:
            # Create user-specified environments
            for env_data in environments_data:
                ProjectEnvironment.objects.create(project=project, **env_data)
        else:
            # Create default environments
            create_default_environments(project)
        
        return project


class OrganisationScopedBindingMixin:
    """Restrict a binding's `project_service` and `integration` to the
    requester's organisation.

    Nothing did this for `integration`, and nothing did it at all on update:
    the viewsets checked `project_service` in perform_create only. An admin
    could bind their service to another organisation's integration — using
    that organisation's SCM or CI/CD credentials to read its repositories and
    pipelines — or PATCH an existing binding onto another organisation's
    service. Scoping the related-field querysets applies one rule to create
    and update alike, and a foreign id fails as DRF's ordinary "object does
    not exist", which says nothing about whether it exists elsewhere.

    With no authenticated organisation in context the querysets are empty,
    so the serializer can still render a binding but cannot write one.
    """

    def get_fields(self):
        fields = super().get_fields()
        request = self.context.get('request')
        organisation = getattr(getattr(request, 'user', None), 'organisation', None)
        fields['project_service'].queryset = ProjectService.objects.filter(
            project__organisation=organisation,
        ) if organisation else ProjectService.objects.none()
        fields['integration'].queryset = ProviderIntegration.objects.filter(
            organisation=organisation,
        ) if organisation else ProviderIntegration.objects.none()
        return fields


class SCMBindingSerializer(OrganisationScopedBindingMixin, serializers.ModelSerializer):
    """
    Serializer for SCM (Source Code Management) bindings.
    
    Links a ProjectService to an SCM provider like GitLab, GitHub, Bitbucket.
    """
    provider_type = serializers.CharField(read_only=True)
    integration_name = serializers.CharField(source='integration.name', read_only=True)
    integration_details = ProviderIntegrationListSerializer(source='integration', read_only=True)
    
    class Meta:
        model = SCMBinding
        fields = [
            'id', 'project_service', 'integration',
            'repository_id', 'repository_name', 'repository_url', 'default_branch',
            'webhook_id', 'webhook_configured',
            'last_sync_at', 'sync_error',
            'created_at', 'updated_at',
            # Read-only computed fields
            'provider_type', 'integration_name', 'integration_details'
        ]
        read_only_fields = [
            'webhook_id', 'webhook_configured', 'last_sync_at', 
            'sync_error', 'created_at', 'updated_at'
        ]
    
    def validate(self, data):
        integration = data.get('integration')
        if integration:
            # Ensure integration supports SCM
            scm_providers = ['gitlab', 'github', 'bitbucket', 'azure_devops']
            if integration.provider_type not in scm_providers:
                raise serializers.ValidationError({
                    'integration': f'Integration must be an SCM provider. Got: {integration.provider_type}'
                })
        return data


class CICDBindingSerializer(OrganisationScopedBindingMixin, serializers.ModelSerializer):
    """
    Serializer for CI/CD bindings.
    
    Links a ProjectService to a CI/CD provider like Jenkins, GitLab CI, Azure Pipelines.
    """
    provider_type = serializers.CharField(read_only=True)
    integration_name = serializers.CharField(source='integration.name', read_only=True)
    integration_details = ProviderIntegrationListSerializer(source='integration', read_only=True)
    binding_type_display = serializers.CharField(source='get_binding_type_display', read_only=True)
    
    class Meta:
        model = CICDBinding
        fields = [
            'id', 'project_service', 'integration', 'binding_type',
            'pipeline_id', 'pipeline_name', 'pipeline_url',
            'auto_trigger', 'trigger_branches',
            'webhook_id', 'webhook_configured',
            'last_sync_at', 'sync_error', 'is_active',
            'created_at', 'updated_at',
            # Read-only computed fields
            'provider_type', 'integration_name', 'integration_details', 'binding_type_display'
        ]
        read_only_fields = [
            'webhook_id', 'webhook_configured', 'last_sync_at',
            'sync_error', 'created_at', 'updated_at'
        ]
    
    def validate(self, data):
        integration = data.get('integration')
        if integration:
            # CI/CD providers include both dedicated and SCM+CI providers
            cicd_providers = ['gitlab', 'github', 'azure_devops', 'jenkins', 'bitbucket', 'argocd', 'flux']
            if integration.provider_type not in cicd_providers:
                raise serializers.ValidationError({
                    'integration': f'Integration must support CI/CD. Got: {integration.provider_type}'
                })
        return data


class ProjectServiceSerializer(serializers.ModelSerializer):
    def get_fields(self):
        # The project, legacy GitLab project and integration must be the
        # requester's organisation's.
        from Utils.scoped_relations import limit_relations
        return limit_relations(
            super().get_fields(), self.context.get('request'),
            project=lambda u, org: Project.objects.filter(organisation=org),
            gitlab_project=lambda u, org: GitlabProject.objects.filter(organisation=org),
            provider_integration=lambda u, org: ProviderIntegration.objects.filter(organisation=org),
        )

    # Include GitLab project details to avoid N+1 frontend requests
    gitlab_project_details = GitlabProjectSerializer(source='gitlab_project', read_only=True)

    # Include bindings in service response
    scm_binding = SCMBindingSerializer(read_only=True)
    cicd_bindings = CICDBindingSerializer(many=True, read_only=True)
    description = serializers.CharField(max_length=500, required=False, allow_blank=True, allow_null=True)

    class Meta:
        model = ProjectService
        fields = [
            'id', 'project', 'service_type', 'name', 'description', 'status',
            'gitlab_project', 'gitlab_project_details', 
            'provider_config', 'provider_integration',
            # New binding fields
            'scm_binding', 'cicd_bindings'
        ]
    
    def validate(self, data):
        service_type = data.get('service_type')
        gitlab_project = data.get('gitlab_project')
        
        if service_type == 'gitlab':
            if not gitlab_project:
                # Unless we are using a global integration (future proofing)
                if not data.get('provider_config') and not data.get('provider_integration'):
                    raise serializers.ValidationError("gitlab_project is required for GitLab services.")
        
        return data