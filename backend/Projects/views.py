from Middlewares.rbac import Requires
import logging
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.decorators import permission_classes
from django.http import Http404
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import Project, ProjectService
from providers.models import GitlabProject, ProviderIntegration
from providers.webhook_service import WebhookService
from providers.code_change_service import CodeChangeService
from rest_framework.permissions import AllowAny
from .serializers import ProjectSerializer, ProjectServiceSerializer, ProjectCreateSerializer
from Data.audit import log_service_action
from Utils.elastic_search import get_elasticsearch_client
import re
import logging
import threading




logger = logging.getLogger(__name__)

class ProjectListView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', POST='project.write')]
    @swagger_auto_schema(
        operation_description="Get a list of all projects for the authenticated user's organization",
        responses={200: ProjectSerializer(many=True)}
    )
    def get(self, request):
        logger.info(f"Project list accessed by user {request.user}")
        projects = Project.objects.filter(organisation=request.user.organisation).prefetch_related(
            'environments',
            'services',
            'services__scm_binding',
            'services__cicd_bindings',
            'services__gitlab_project',
        )
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Create a new project with optional environments",
        request_body=ProjectCreateSerializer,
        responses={201: ProjectSerializer}
    )
    def post(self, request):
        logger = logging.getLogger(__name__)
        
        logger.warning(f"Project creation attempted by user {request.user}")
        
        # Use ProjectCreateSerializer for handling environments
        data = request.data.copy()
        data['organisation'] = request.user.organisation.id
        
        serializer = ProjectCreateSerializer(data=data)
        if serializer.is_valid():
            project = serializer.save()
            
            # Create indices in background thread
            def create_indices_async(project_id):
                import re
                from Utils.elastic_search import get_elasticsearch_client
                from .models import Project
                
                try:
                    project = Project.objects.get(id=project_id)
                    es_client = get_elasticsearch_client()
                    
                    # Sanitize project name
                    sanitized_name = project.name.lower().replace(' ', '-').replace('_', '-')
                    sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '-')
                    sanitized_name = sanitized_name.strip('-')
                    sanitized_name = re.sub(r'-+', '-', sanitized_name)
                    
                    cicd_index_name = f"ci_cd-logs-{sanitized_name}"
                    app_logs_index_name = f"application-logs-{sanitized_name}"
                    
                    logger.info(f"Background: Creating indices for project {project_id}")
                    
                    # Define mappings
                    cicd_mapping = {
                        "mappings": {
                            "properties": {
                                "@timestamp": {"type": "date"},
                                "message": {"type": "text"},
                                "log_source": {"type": "keyword"},
                                "level": {"type": "keyword"},
                                "project_id": {"type": "keyword"},
                                "project_name": {"type": "keyword"},
                                "pipeline_id": {"type": "keyword"},
                                "job_id": {"type": "keyword"},
                                "job_name": {"type": "keyword"},
                                "status": {"type": "keyword"},
                                "error_details": {"type": "text"}
                            }
                        }
                    }
                    
                    app_logs_mapping = {
                        "mappings": {
                            "properties": {
                                "@timestamp": {"type": "date"},
                                "timestamp": {"type": "date"},
                                "message": {"type": "text"},
                                "levelname": {"type": "keyword"},
                                "logger": {"type": "keyword"},
                                "pathname": {"type": "text"},
                                "funcName": {"type": "keyword"},
                                "lineno": {"type": "integer"},
                                "service_name": {"type": "keyword"},
                                "project_folder": {"type": "keyword"},
                                "project_name": {"type": "keyword"},
                                "index_name": {"type": "keyword"}
                            }
                        }
                    }
                    
                    # Create indices
                    if not es_client.indices.exists(index=cicd_index_name):
                        es_client.indices.create(index=cicd_index_name, body=cicd_mapping)
                        logger.info(f"Background: Created CI/CD index: {cicd_index_name}")
                    
                    if not es_client.indices.exists(index=app_logs_index_name):
                        es_client.indices.create(index=app_logs_index_name, body=app_logs_mapping)
                        logger.info(f"Background: Created app logs index: {app_logs_index_name}")
                    
                    # Update project
                    project.es_index_name = cicd_index_name
                    project.app_logs_index_name = app_logs_index_name
                    project.save()
                    
                    logger.info(f"Background: Successfully created indices for project {project_id}")
                    
                except Exception as e:
                    logger.error(f"Background: Error creating indices for project {project_id}: {str(e)}", exc_info=True)
            
            # Start background thread
            thread = threading.Thread(target=create_indices_async, args=(project.id,))
            thread.daemon = True
            thread.start()
            
            logger.info(f"Project '{project.name}' created with {project.environments.count()} environments. Elasticsearch indices creation started in background.")
            
            # Return with environments included
            return Response(ProjectSerializer(project).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', PUT='project.write', DELETE='project.delete')]

    def get_object(self, request, pk):
        """Fetch the project scoped to the caller's organisation.

        Returns None if the project doesn't exist or belongs to another
        org — callers turn that into a 404 (identical response for
        "doesn't exist" and "wrong org" so there's no cross-org
        enumeration oracle). Previous version fetched unscoped and
        returned 403 on org mismatch, which leaked the fact that a
        project ID was assigned to some org somewhere.
        """
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return None
        qs = Project.objects.all()
        qs = qs.filter(organisation=user_org)
        return qs.filter(pk=pk).first()

    @swagger_auto_schema(
        operation_description="Get details of a specific project",
        responses={200: ProjectSerializer}
    )
    def get(self, request, pk):
        project = self.get_object(request, pk)
        if project is None:
            return Response({"error": "Project not found"},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = ProjectSerializer(project)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Update a project",
        request_body=ProjectSerializer,
        responses={200: ProjectSerializer}
    )
    def put(self, request, pk):
        project = self.get_object(request, pk)
        if project is None:
            return Response({"error": "Project not found"},
                            status=status.HTTP_404_NOT_FOUND)

        # Handle environments update if provided
        environments_data = request.data.get('environments', None)
        if environments_data is not None:
            from .models import ProjectEnvironment
            
            # Delete existing environments
            project.environments.all().delete()
            
            # Create new environments
            for env_data in environments_data:
                ProjectEnvironment.objects.create(
                    project=project,
                    name=env_data.get('name'),
                    display_name=env_data.get('display_name', env_data.get('name', '').title()),
                    branch_patterns=env_data.get('branch_patterns', []),
                    tag_patterns=env_data.get('tag_patterns', []),
                    log_label_value=env_data.get('log_label_value', ''),
                    is_active=env_data.get('is_active', True),
                )
            logger.info(f"Updated project '{project.name}' with {len(environments_data)} environments")
        
        # Update project fields
        serializer = ProjectSerializer(project, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            # Re-fetch to include updated environments
            project.refresh_from_db()
            return Response(ProjectSerializer(project).data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_description="Delete a project",
        responses={204: "No content"}
    )
    def delete(self, request, pk):
        project = self.get_object(request, pk)
        if project is None:
            return Response({"error": "Project not found"},
                            status=status.HTTP_404_NOT_FOUND)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

class ProjectServiceView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', POST='project.write')]
    @swagger_auto_schema(
        operation_description="Get all services for a specific project",
        manual_parameters=[
            openapi.Parameter('project_id', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER, required=True)
        ],
        responses={200: ProjectServiceSerializer(many=True)}
    )
    def get(self, request, project_id):
        # Org-scoped lookup — fetch-then-check leaked project existence
        # across orgs (attacker enumerates IDs by comparing 403 vs 404).
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        qs = Project.objects.all()
        qs = qs.filter(organisation=user_org)
        project = qs.filter(pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        services = ProjectService.objects.filter(project=project).select_related('gitlab_project', 'provider_integration')
        serializer = ProjectServiceSerializer(services, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Add a service to a project",
        manual_parameters=[
            openapi.Parameter('project_id', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER, required=True)
        ],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['service_type', 'name'],
            properties={
                'service_type': openapi.Schema(type=openapi.TYPE_STRING),
                'name': openapi.Schema(type=openapi.TYPE_STRING),
                'description': openapi.Schema(type=openapi.TYPE_STRING),
                'gitlab_project': openapi.Schema(type=openapi.TYPE_INTEGER),
            }
        ),
        responses={201: ProjectServiceSerializer}
    )
    def post(self, request, project_id):
        # Org-scoped project lookup — the previous fetch-then-check
        # distinguished 403 vs 404 based on cross-org existence.
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        project_qs = Project.objects.all()
        project_qs = project_qs.filter(organisation=user_org)
        project = project_qs.filter(pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        data['project'] = project_id

        # 1. Handle Global Integration (New Architecture)
        integration_id = request.data.get('integration_id')
        repository_id = request.data.get('repository_id')

        if integration_id:
            integration_qs = ProviderIntegration.objects.all()
            integration_qs = integration_qs.filter(organisation=user_org)
            integration = integration_qs.filter(pk=integration_id).first()
            if integration is None:
                return Response({"error": "Integration not found"}, status=status.HTTP_404_NOT_FOUND)

            data['provider_integration'] = integration.id

            serializer = ProjectServiceSerializer(data=data, context={'request': request})
            if serializer.is_valid():
                service = serializer.save()

                # Create SCM Binding if repository info provided
                if repository_id:
                    from .models import SCMBinding
                    SCMBinding.objects.create(
                        project_service=service,
                        integration=integration,
                        repository_id=repository_id,
                        repository_name=request.data.get('repository_name', repository_id),
                        active_branch=request.data.get('default_branch', 'main')
                    )

                self._create_indices(project)

                log_service_action(request, 'SERVICE_CREATE', service.name, service_id=service.id, details={
                    'type': service.service_type,
                    'integration_id': integration.id
                })

                return Response(serializer.data, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        # Fallback/Standard handling
        serializer = ProjectServiceSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            service = serializer.save()

            if not project.es_index_name:
                self._create_indices(project)

            log_service_action(request, 'SERVICE_CREATE', service.name, service_id=service.id, details={
                'type': service.service_type,
                'project_id': project_id
            })

            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def _create_indices(self, project):
        """Helper to check and create ES indices if missing"""
        if not project.es_index_name:
            try:
                from Utils.elastic_search import get_elasticsearch_client
                es_client = get_elasticsearch_client()
                
                # Sanitize project name for Elasticsearch index
                sanitized_name = project.name.lower().replace(' ', '_').replace('-', '_')
                sanitized_name = ''.join(c for c in sanitized_name if c.isalnum() or c == '_')
                index_name = f"ci_cd-logs-project-{sanitized_name}"

                # Define index mapping with appropriate fields for log data
                mapping = {
                    "mappings": {
                        "properties": {
                            "@timestamp": {"type": "date_nanos"},
                            "message": {"type": "text"},
                            "log_source": {"type": "keyword"},
                            "level": {"type": "keyword"},
                            "project_id": {"type": "keyword"},
                            "pipeline_id": {"type": "keyword"},
                            "job_id": {"type": "keyword"},
                            "job_name": {"type": "keyword"},
                            "status": {"type": "keyword"},
                            "error_details": {"type": "text"}
                        }
                    }
                }
                
                if not es_client.indices.exists(index=index_name):
                    es_client.indices.create(index=index_name, body=mapping)
                    project.es_index_name = index_name
                    project.save()
                    logger.info(f"Created fallback ES index for project {project.id}: {index_name}")
            except Exception as e:
                logger.error(f"Error creating Elasticsearch index: {str(e)}")



class ProjectServiceDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', PUT='project.write', PATCH='project.write', DELETE='project.delete')]

    def get_object(self, request, pk):
        """Fetch the service scoped to the caller's organisation via project FK.

        Returns None for cross-org / missing so callers return 404.
        Prior fetch-then-check returned 403 with a distinguishing
        message, letting an attacker enumerate service IDs across orgs.
        """
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return None
        qs = ProjectService.objects.all()
        qs = qs.filter(project__organisation=user_org)
        return qs.filter(pk=pk).first()

    @swagger_auto_schema(
        operation_description="Get details of a specific project service",
        responses={200: ProjectServiceSerializer}
    )
    def get(self, request, pk):
        service = self.get_object(request, pk)
        if service is None:
            return Response({"error": "Service not found"},
                            status=status.HTTP_404_NOT_FOUND)
        serializer = ProjectServiceSerializer(service)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Update fields on a project service (partial). "
                              "Editable fields: name, description, status, "
                              "service_type, subtype, provider_config.",
        request_body=ProjectServiceSerializer,
        responses={200: ProjectServiceSerializer, 400: "Validation error",
                   404: "Not found"},
    )
    def patch(self, request, pk):
        return self._update(request, pk, partial=True)

    @swagger_auto_schema(
        operation_description="Replace all editable fields on a project service.",
        request_body=ProjectServiceSerializer,
        responses={200: ProjectServiceSerializer, 400: "Validation error",
                   404: "Not found"},
    )
    def put(self, request, pk):
        return self._update(request, pk, partial=False)

    def _update(self, request, pk, partial: bool):
        """Shared PATCH/PUT handler.

        Editable fields deliberately EXCLUDE ``project`` — moving a
        service between projects would silently transfer its
        SCMBinding, CICDBindings, historical batches, and issues.
        That's an operation with enough blast radius to warrant a
        dedicated ``/move`` endpoint if we ever need it.
        Cross-org protection: base queryset scoped to caller's org.
        """
        service = self.get_object(request, pk)
        if service is None:
            return Response({"error": "Service not found"},
                            status=status.HTTP_404_NOT_FOUND)

        # Whitelist editable fields — the serializer accepts more but
        # some (project, gitlab_project, provider_integration) shouldn't
        # be mutable via a generic edit form.
        editable = {'name', 'description', 'status', 'service_type',
                    'subtype', 'provider_config'}
        data = {k: v for k, v in request.data.items() if k in editable}

        serializer = ProjectServiceSerializer(service, data=data, partial=partial, context={'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors,
                            status=status.HTTP_400_BAD_REQUEST)

        pre_name = service.name
        updated = serializer.save()
        # Audit log — mirrors the SERVICE_DELETE + create paths.
        log_service_action(
            request, 'SERVICE_UPDATE', updated.name,
            service_id=updated.id,
            details={'previous_name': pre_name,
                     'changed_fields': list(data.keys())},
        )
        return Response(ProjectServiceSerializer(updated).data)

    @swagger_auto_schema(
        operation_description="Delete a project service",
        responses={204: "No content"}
    )
    def delete(self, request, pk):
        service = self.get_object(request, pk)
        if service is None:
            return Response({"error": "Service not found"},
                            status=status.HTTP_404_NOT_FOUND)
        
        # Get the GitLab project before deleting the service
        gitlab_project = service.gitlab_project
        
        # Capture details before delete
        service_name = service.name
        service_id = service.id
        service_type = service.service_type
        project_id = service.project.id
        
        # Delete the service
        service.delete()
        
        # Log service delete
        log_service_action(request, 'SERVICE_DELETE', service_name, service_id=service_id, details={
            'type': service_type,
            'project_id': project_id
        })
        
        # Check if the GitLab project is still referenced by any other services
        if gitlab_project and not ProjectService.objects.filter(gitlab_project=gitlab_project).exists():
            # If no other projects are using this GitLab project, delete it
            gitlab_project.delete()
        
        return Response(status=status.HTTP_204_NO_CONTENT)


#costum servuce
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from drf_yasg.utils import swagger_auto_schema
from drf_yasg import openapi
from .models import Project, ProjectService
from .serializers import ProjectServiceSerializer

class CustomServiceView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read', POST='project.write')]
    @swagger_auto_schema(
        operation_description="Get all custom services for a specific project",
        manual_parameters=[
            openapi.Parameter('project_id', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER, required=True)
        ],
        responses={200: ProjectServiceSerializer(many=True)}
    )
    def get(self, request, project_id):
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        qs = Project.objects.all()
        qs = qs.filter(organisation=user_org)
        project = qs.filter(pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        services = ProjectService.objects.filter(project=project, service_type='custom')
        serializer = ProjectServiceSerializer(services, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Add a custom service to a project",
        manual_parameters=[
            openapi.Parameter('project_id', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER, required=True)
        ],
        request_body=ProjectServiceSerializer,
        responses={
            201: ProjectServiceSerializer,
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found"
        }
    )
    def post(self, request, project_id):
        user_org = getattr(request.user, 'organisation', None)
        if not user_org:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        qs = Project.objects.all()
        qs = qs.filter(organisation=user_org)
        project = qs.filter(pk=project_id).first()
        if project is None:
            return Response({"error": "Project not found"}, status=status.HTTP_404_NOT_FOUND)

        data = request.data.copy()
        data['project'] = project_id
        data['service_type'] = 'custom'

        serializer = ProjectServiceSerializer(data=data, context={'request': request})
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class ProjectLogConfigView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='project.read')]
    @swagger_auto_schema(
        operation_description="Get log configuration for all projects (for Fluentd configuration)",
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'projects': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'project_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'project_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'sanitized_name': openapi.Schema(type=openapi.TYPE_STRING),
                                'log_folder_path': openapi.Schema(type=openapi.TYPE_STRING),
                                'app_logs_index': openapi.Schema(type=openapi.TYPE_STRING),
                                'cicd_logs_index': openapi.Schema(type=openapi.TYPE_STRING),
                                'services': openapi.Schema(
                                    type=openapi.TYPE_ARRAY,
                                    items=openapi.Schema(
                                        type=openapi.TYPE_OBJECT,
                                        properties={
                                            'service_id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                            'service_name': openapi.Schema(type=openapi.TYPE_STRING),
                                            'log_file_path': openapi.Schema(type=openapi.TYPE_STRING),
                                        }
                                    )
                                )
                            }
                        )
                    )
                }
            )
        }
    )
    def get(self, request):
        """Get mapping of projects and their log paths/indices"""
        projects = Project.objects.filter(organisation=request.user.organisation)
        
        project_configs = []
        for project in projects:
            services = ProjectService.objects.filter(project=project)
            service_list = [
                {
                    'service_id': service.id,
                    'service_name': service.name or f'Service {service.id}',
                    'service_type': service.service_type,
                    'log_file_path': service.get_log_file_path()
                }
                for service in services
            ]
            
            project_configs.append({
                'project_id': project.id,
                'project_name': project.name,
                'sanitized_name': project.get_sanitized_name(),
                'log_folder_path': project.get_log_folder_path(),
                'app_logs_index': project.app_logs_index_name,
                'cicd_logs_index': project.es_index_name,
                'services': service_list
            })
        
        return Response({'projects': project_configs})


# ============================================================================
# SCM + CI/CD Binding Views (Multi-Provider Support)
# ============================================================================

from rest_framework import viewsets
from rest_framework.decorators import action
from .models import SCMBinding, CICDBinding
from .serializers import SCMBindingSerializer, CICDBindingSerializer


class SCMBindingViewSet(viewsets.ModelViewSet):
    """
    API for managing SCM (Source Code Management) bindings.
    
    Allows linking a ProjectService to an SCM provider (GitLab, GitHub, etc.)
    separately from CI/CD, enabling multi-provider configurations.
    
    Endpoints:
    - GET    /api/scm-bindings/                    - List all SCM bindings
    - POST   /api/scm-bindings/                    - Create new binding
    - GET    /api/scm-bindings/{id}/               - Get binding details
    - PUT    /api/scm-bindings/{id}/               - Update binding
    - DELETE /api/scm-bindings/{id}/               - Delete binding
    - POST   /api/scm-bindings/{id}/sync/          - Sync commits from SCM
    - POST   /api/scm-bindings/{id}/setup-webhook/ - Configure webhook
    """
    serializer_class = SCMBindingSerializer
    permission_classes = [IsAuthenticated, Requires(GET='project.read', default='project.write')]
    
    def get_queryset(self):
        """Filter SCM bindings by user's organisation."""
        return SCMBinding.objects.filter(
            project_service__project__organisation=self.request.user.organisation
        ).select_related('integration', 'project_service', 'project_service__project')
    
    def create(self, request, *args, **kwargs):
        """Create SCM binding, handling OneToOne constraint violations."""
        from django.db import IntegrityError

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError:
            return Response(
                {'project_service': ['This service already has an SCM binding.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        # Organisation scoping of project_service and integration lives in
        # the serializer (OrganisationScopedBindingMixin), for update too.
        binding = serializer.save()

        # Log the action
        log_service_action(
            self.request, 'SCM_BINDING_CREATE',
            binding.repository_name or binding.repository_id,
            details={
                'project_service_id': binding.project_service.id,
                'integration_id': binding.integration.id,
                'provider': binding.provider_type
            }
        )
    
    def perform_destroy(self, instance):
        """Log deletion before destroying."""
        log_service_action(
            self.request, 'SCM_BINDING_DELETE',
            instance.repository_name or instance.repository_id,
            details={
                'project_service_id': instance.project_service.id,
                'integration_id': instance.integration.id
            }
        )
        instance.delete()
    
    @action(detail=True, methods=['post'], url_path='sync')
    def sync(self, request, pk=None):
        """
        Sync commits from the SCM provider.

        Uses cursor-based pagination:
          - On first sync or full re-sync: fetches last 7 days.
          - On subsequent syncs: fetches from last_sync_at onward.
          - Returns next_cursor for frontend pagination if there are more results.
        """
        binding = self.get_object()

        try:
            from providers.scm_providers import SCMProviderError
            from datetime import datetime, timedelta

            provider = binding.get_provider()

            # Determine start cursor: use last_sync_at if available, else 7 days
            since = binding.last_sync_at or (datetime.now() - timedelta(days=7))
            limit = 100

            commits = provider.get_commits(since=since, limit=limit)

            # Save fetched commits
            if commits:
                CodeChangeService.save_commits_from_webhook(
                    provider=binding.provider_type,
                    project_id=binding.repository_id,
                    commits=commits,
                    gitlab_project=None,
                )

            # Update sync status
            binding.last_sync_at = datetime.now()
            binding.sync_error = ''
            binding.save()

            # Provide a cursor hint if the result set was full (more may exist)
            has_more = len(commits) >= limit
            next_cursor = commits[-1].get('timestamp') if has_more and commits else None

            return Response({
                'success': True,
                'commits_fetched': len(commits),
                'has_more': has_more,
                'next_cursor': next_cursor,
                'commits': commits[:10],
            })

        except SCMProviderError as e:
            binding.sync_error = str(e)
            binding.save()
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(f"SCM sync failed: {e}")
            return Response({
                'success': False,
                'error': f'Sync failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='setup-webhook')
    def setup_webhook(self, request, pk=None):
        """
        Configure webhook on the SCM provider.
        
        Automatically creates a webhook to receive push events.
        """
        binding = self.get_object()
        user_host = request.build_absolute_uri('/')
        
        result = WebhookService.setup_scm_webhook(binding, user_host)
        
        if result['success']:
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['get'], url_path='auto-link-suggestions')
    def auto_link_suggestions(self, request, pk=None):
        """
        Get CI/CD binding suggestions for this SCM.
        
        Detects pipelines/workflows in the same repository and suggests
        CICDBinding creation for unified providers (GitLab, GitHub, etc.)
        """
        binding = self.get_object()
        
        try:
            from providers.services import AutoLinkService
            
            service = AutoLinkService(binding)
            
            if not service.can_auto_link():
                return Response({
                    'can_auto_link': False,
                    'message': f'Provider {binding.provider_type} does not support integrated CI/CD',
                    'suggestions': []
                })
            
            suggestions = service.get_cicd_suggestions()
            
            return Response({
                'can_auto_link': True,
                'provider_type': binding.provider_type,
                'repository': binding.repository_name or binding.repository_id,
                'suggestions': suggestions,
                'count': len(suggestions)
            })
            
        except Exception as e:
            logger.exception(f"Auto-link detection failed: {e}")
            return Response({
                'can_auto_link': False,
                'error': str(e),
                'suggestions': []
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='auto-link')
    def auto_link(self, request, pk=None):
        """
        Create CI/CD bindings from suggestions.
        
        Accepts suggestion IDs and creates CICDBinding instances.
        """
        binding = self.get_object()
        suggestion_ids = request.data.get('suggestion_ids', [])
        
        try:
            from providers.services import AutoLinkService
            
            service = AutoLinkService(binding)
            suggestions = service.get_cicd_suggestions()
            
            # Filter to selected suggestions
            if suggestion_ids:
                suggestions = [s for s in suggestions if s.get('pipeline_id') in suggestion_ids]
            
            # Create bindings
            created = service.create_suggested_bindings(suggestions, binding.project_service)
            
            return Response({
                'success': True,
                'created_count': len(created),
                'created': [
                    {
                        'id': b.id,
                        'pipeline_name': b.pipeline_name,
                        'binding_type': b.binding_type
                    }
                    for b in created
                ]
            })
            
        except Exception as e:
            logger.exception(f"Auto-link creation failed: {e}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class CICDBindingViewSet(viewsets.ModelViewSet):
    """
    API for managing CI/CD bindings.
    
    Allows linking a ProjectService to a CI/CD provider (Jenkins, GitLab CI, etc.)
    Multiple bindings per service are supported (build, deploy, test pipelines).
    
    Endpoints:
    - GET    /api/cicd-bindings/                     - List all CI/CD bindings
    - POST   /api/cicd-bindings/                     - Create new binding
    - GET    /api/cicd-bindings/{id}/                - Get binding details
    - PUT    /api/cicd-bindings/{id}/                - Update binding
    - DELETE /api/cicd-bindings/{id}/                - Delete binding
    - POST   /api/cicd-bindings/{id}/sync/           - Sync builds from CI/CD
    - POST   /api/cicd-bindings/{id}/trigger/        - Trigger a build
    """
    serializer_class = CICDBindingSerializer
    permission_classes = [IsAuthenticated, Requires(GET='project.read', default='project.write')]
    
    def get_queryset(self):
        """Filter CI/CD bindings by user's organisation."""
        queryset = CICDBinding.objects.filter(
            project_service__project__organisation=self.request.user.organisation
        ).select_related('integration', 'project_service', 'project_service__project')
        
        # Optional filtering by project_service
        project_service_id = self.request.query_params.get('project_service')
        if project_service_id:
            queryset = queryset.filter(project_service_id=project_service_id)
        
        # Optional filtering by binding_type
        binding_type = self.request.query_params.get('binding_type')
        if binding_type:
            queryset = queryset.filter(binding_type=binding_type)
        
        return queryset
    
    def create(self, request, *args, **kwargs):
        """Create CICD binding and return webhook_secret in response."""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        data = serializer.data
        # Include webhook_secret in the creation response only
        binding = CICDBinding.objects.get(pk=data['id'])
        data['webhook_secret'] = binding.webhook_secret
        headers = self.get_success_headers(serializer.data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        # Organisation scoping of project_service and integration lives in
        # the serializer (OrganisationScopedBindingMixin), for update too.
        binding = serializer.save()

        # Auto-generate webhook secret on creation
        binding.webhook_secret = WebhookService.generate_secret()
        binding.save(update_fields=['webhook_secret'])

        log_service_action(
            self.request, 'CICD_BINDING_CREATE',
            binding.pipeline_name or binding.pipeline_id,
            details={
                'project_service_id': binding.project_service.id,
                'integration_id': binding.integration.id,
                'provider': binding.provider_type,
                'binding_type': binding.binding_type
            }
        )

    def perform_destroy(self, instance):
        """Log deletion before destroying."""
        log_service_action(
            self.request, 'CICD_BINDING_DELETE',
            instance.pipeline_name or instance.pipeline_id,
            details={
                'project_service_id': instance.project_service.id,
                'integration_id': instance.integration.id
            }
        )
        instance.delete()

    @action(detail=True, methods=['post'], url_path='setup-webhook')
    def setup_webhook(self, request, pk=None):
        """
        Configure webhook on the CI/CD provider.

        Automatically creates a webhook to receive pipeline/job events.
        """
        binding = self.get_object()
        host_url = request.build_absolute_uri('/')

        result = WebhookService.setup_cicd_webhook(binding, host_url)

        if result['success']:
            return Response(result)
        else:
            return Response(result, status=status.HTTP_400_BAD_REQUEST)
    
    @action(detail=True, methods=['post'], url_path='sync')
    def sync(self, request, pk=None):
        """
        Sync builds/pipelines from the CI/CD provider.

        Supports Jenkins (via list_projects) and SCM+CI providers
        (GitLab pipelines, GitHub Actions workflow runs) via their
        native APIs.
        """
        binding = self.get_object()

        try:
            from providers.scm_providers import SCMProviderError, CICD_PROVIDERS
            from datetime import datetime
            import requests as http_requests

            provider = binding.get_provider()
            provider_type = binding.integration.provider_type

            # --- Jenkins ---
            if provider_type in CICD_PROVIDERS:
                builds = provider.list_projects(search=binding.pipeline_id)
                binding.last_sync_at = datetime.now()
                binding.sync_error = ''
                binding.save()
                return Response({
                    'success': True,
                    'jobs_found': len(builds),
                    'jobs': builds[:5],
                })

            # --- GitLab CI ---
            if provider_type == 'gitlab':
                project_id = binding.pipeline_id or (
                    binding.project_service.scm_binding.repository_id
                    if hasattr(binding.project_service, 'scm_binding') else None
                )
                if not project_id:
                    return Response({'success': False, 'error': 'No project ID configured'}, status=400)

                base_url = binding.integration.get_decrypted_base_url()
                headers = {'PRIVATE-TOKEN': binding.integration.get_decrypted_token()}
                resp = http_requests.get(
                    f'{base_url}/api/v4/projects/{project_id}/pipelines',
                    headers=headers,
                    params={'per_page': 20, 'order_by': 'updated_at', 'sort': 'desc'},
                    timeout=15,
                )
                resp.raise_for_status()
                pipelines = resp.json()

                binding.last_sync_at = datetime.now()
                binding.sync_error = ''
                binding.save()
                return Response({
                    'success': True,
                    'pipelines_found': len(pipelines),
                    'pipelines': [
                        {
                            'id': p.get('id'),
                            'status': p.get('status'),
                            'ref': p.get('ref'),
                            'sha': p.get('sha', '')[:8],
                            'created_at': p.get('created_at'),
                            'web_url': p.get('web_url'),
                        }
                        for p in pipelines[:10]
                    ],
                })

            # --- GitHub Actions ---
            if provider_type == 'github':
                repo = binding.pipeline_id or (
                    binding.project_service.scm_binding.repository_id
                    if hasattr(binding.project_service, 'scm_binding') else None
                )
                if not repo:
                    return Response({'success': False, 'error': 'No repository configured'}, status=400)

                base_url = binding.integration.get_decrypted_base_url() or 'https://api.github.com'
                headers = {
                    'Authorization': f'Bearer {binding.integration.get_decrypted_token()}',
                    'Accept': 'application/vnd.github+json',
                }
                resp = http_requests.get(
                    f'{base_url}/repos/{repo}/actions/runs',
                    headers=headers,
                    params={'per_page': 20},
                    timeout=15,
                )
                resp.raise_for_status()
                data = resp.json()
                runs = data.get('workflow_runs', [])

                binding.last_sync_at = datetime.now()
                binding.sync_error = ''
                binding.save()
                return Response({
                    'success': True,
                    'runs_found': len(runs),
                    'runs': [
                        {
                            'id': r.get('id'),
                            'name': r.get('name'),
                            'status': r.get('status'),
                            'conclusion': r.get('conclusion'),
                            'head_branch': r.get('head_branch'),
                            'created_at': r.get('created_at'),
                            'html_url': r.get('html_url'),
                        }
                        for r in runs[:10]
                    ],
                })

            return Response({
                'success': True,
                'message': f'Sync not yet implemented for provider type: {provider_type}',
            })

        except SCMProviderError as e:
            binding.sync_error = str(e)
            binding.save()
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception(f"CI/CD sync failed: {e}")
            binding.sync_error = str(e)
            binding.save()
            return Response({
                'success': False,
                'error': f'Sync failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    @action(detail=True, methods=['post'], url_path='trigger')
    def trigger(self, request, pk=None):
        """
        Trigger a build on the CI/CD provider.
        
        For Jenkins, triggers a build with optional parameters.
        """
        binding = self.get_object()
        
        try:
            from providers.scm_providers import CICD_PROVIDERS
            
            if binding.integration.provider_type in CICD_PROVIDERS:
                provider = binding.get_provider()
                
                # Get optional build parameters
                parameters = request.data.get('parameters', {})
                
                result = provider.trigger_build(binding.pipeline_id, parameters)
                
                if result.get('success'):
                    return Response({
                        'success': True,
                        'message': 'Build triggered',
                        'queue_url': result.get('queue_url')
                    })
                else:
                    return Response({
                        'success': False,
                        'error': result.get('error', 'Unknown error')
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'success': False,
                    'error': 'Trigger not supported for this provider'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except Exception as e:
            logger.exception(f"CI/CD trigger failed: {e}")
            return Response({
                'success': False,
                'error': f'Trigger failed: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SCMWebhookReceiverView(APIView):
    """
    Public endpoint for receiving webhooks from SCM providers.

    URL: /api/webhooks/scm/{binding_id}/
    Validates HMAC signatures when a webhook_secret is configured.
    """
    permission_classes = [AllowAny]

    @staticmethod
    def _verify_signature(request, binding):
        """
        Verify the webhook signature against the stored secret.

        Supports:
          - GitLab: X-Gitlab-Token (plain token comparison)
          - GitHub: X-Hub-Signature-256 (HMAC-SHA256)
          - Bitbucket: X-Hub-Signature (HMAC-SHA256)

Rejects when no secret is configured (fail closed).
        """
        import hmac
        import hashlib

        secret = binding.webhook_secret
        if not secret:
            # Fail closed: a binding with no secret can't authenticate any
            # caller. New bindings always get one (see SCMBinding.save);
            # this guards the rare legacy row until it is re-set up.
            logger.warning("SCM binding %s has no webhook_secret — rejecting", binding.pk)
            return False

        # GitLab uses a simple token header
        gitlab_token = request.headers.get('X-Gitlab-Token')
        if gitlab_token:
            return hmac.compare_digest(gitlab_token, secret)

        # GitHub / Bitbucket use HMAC-SHA256
        sig_header = (
            request.headers.get('X-Hub-Signature-256')
            or request.headers.get('X-Hub-Signature')
        )
        if sig_header:
            expected = 'sha256=' + hmac.new(
                secret.encode(), request.body, hashlib.sha256
            ).hexdigest()
            return hmac.compare_digest(sig_header, expected)

        # No recognised signature header — reject when secret is set
        return False

    def post(self, request, binding_id):
        try:
            binding = SCMBinding.objects.get(pk=binding_id)

            # Verify webhook signature
            if not self._verify_signature(request, binding):
                logger.warning("Webhook signature verification failed for binding %s", binding_id)
                return Response(
                    {'error': 'Invalid webhook signature'},
                    status=status.HTTP_403_FORBIDDEN,
                )

            # Identify event type
            event_type = 'push'
            if 'X-Gitlab-Event' in request.headers:
                event_type = request.headers['X-Gitlab-Event'].replace(' Hook', '').lower().replace(' ', '_')
            elif 'X-GitHub-Event' in request.headers:
                event_type = request.headers['X-GitHub-Event']

            logger.info(f"Received webhook for binding {binding_id} ({event_type})")

            result = WebhookService.process_scm_payload(binding, request.data, event_type)

            status_code = status.HTTP_200_OK if result['success'] else status.HTTP_400_BAD_REQUEST
            return Response(result, status=status_code)

        except SCMBinding.DoesNotExist:
            return Response({'error': 'Binding not found'}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            logger.exception(f"Webhook receiver error: {e}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ProjectDeploymentViewSet(viewsets.ModelViewSet):
    """CRUD for ProjectDeployment (Batch 52 — Deployment model UI).

    Endpoints (under /api/project-deployments/):
        GET    /                            — list (org-scoped)
        POST   /                            — create
        GET    /{id}/                       — detail
        PATCH  /{id}/                       — update
        DELETE /{id}/                       — delete
        GET    /suggest/?cluster=<id>       — suggest deployments to
                                              create when a new cluster
                                              is added (per user's
                                              "suggest, don't auto-create"
                                              design decision — Batch 48).

    Reads: any authenticated org member.
    Writes: any authenticated org member with write role — deployments
    are per-project operational config, not global admin surface, so
    project.read to list, project.write to change (Middlewares/rbac.py).

    Tenant isolation: get_queryset filters by
    ``project__organisation=request.user.organisation``. Serializer
    validates that the target project belongs to the caller's org on
    create + update so a crafted POST can't cross-org.
    """
    from .serializers import ProjectDeploymentSerializer
    from .models import ProjectDeployment as _PD

    serializer_class = ProjectDeploymentSerializer
    permission_classes = [IsAuthenticated, Requires(GET='project.read', default='project.write')]

    def get_queryset(self):
        user_org = getattr(self.request.user, 'organisation', None)
        if user_org is None:
            return self._PD.objects.none()
        qs = self._PD.objects.filter(
            project__organisation=user_org,
        ).select_related('project', 'environment', 'cluster')
        # Optional filter by project id (frontend Deployments tab uses this).
        project_id = self.request.query_params.get('project')
        if project_id:
            qs = qs.filter(project_id=project_id)
        return qs.order_by('project__name', 'name')

    def create(self, request, *args, **kwargs):
        from django.db import IntegrityError
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            self.perform_create(serializer)
        except IntegrityError as exc:
            # Unique-shape or unique-name violation — return clean 400
            # with a specific message so the UI can highlight the right
            # field. Falls back to a generic message if we can't tell.
            msg = str(exc)
            if 'uniq_project_deployment_shape' in msg:
                return Response(
                    {'non_field_errors': [
                        'A deployment with this exact env / cluster / '
                        'region / namespace combination already exists.'
                    ]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if 'uniq_project_deployment_name' in msg:
                return Response(
                    {'name': [
                        'A deployment with this name already exists for '
                        'this project.'
                    ]},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            return Response(
                {'non_field_errors': ['Invalid deployment configuration.']},
                status=status.HTTP_400_BAD_REQUEST,
            )
        headers = self.get_success_headers(serializer.data)
        return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)

    @action(detail=False, methods=['get'])
    def suggest(self, request):
        """Suggest deployments to create for a newly-registered cluster.

        Per Batch 48 design decision ("suggest, don't auto-create"): when
        a user adds a Cluster, we don't silently create deployments for
        every existing project. Instead the frontend calls this endpoint
        to compute suggestions the user can accept or reject.

        Query params:
            cluster: cluster id (required) — the newly-registered cluster.

        Response:
            {
              "cluster_id": <int>,
              "suggestions": [
                {"project_id": <int>, "project_name": "...",
                 "environment_id": <int>, "environment_name": "production",
                 "reason": "..."},
                ...
              ]
            }

        The frontend renders these as a "want to create these deployments
        for the new cluster?" modal with per-row accept/reject.
        """
        cluster_id = request.query_params.get('cluster')
        if not cluster_id:
            return Response(
                {'error': 'cluster query param required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from integrations.models import Cluster as _Cluster
        user_org = getattr(request.user, 'organisation', None)
        if user_org is None:
            return Response({'cluster_id': cluster_id, 'suggestions': []})
        cluster = _Cluster.objects.filter(pk=cluster_id, organisation=user_org).first()
        if cluster is None:
            return Response(
                {'error': 'Cluster not found'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Suggest: for each project without a deployment on this cluster
        # yet, propose one row per (project × active_env). Skip envs that
        # already have a deployment on this cluster.
        from .models import Project as _Project, ProjectEnvironment as _PE
        suggestions = []
        for proj in _Project.objects.filter(organisation=user_org).only('id', 'name'):
            existing_env_ids = set(
                self._PD.objects.filter(
                    project=proj, cluster=cluster,
                ).values_list('environment_id', flat=True)
            )
            for env in _PE.objects.filter(project=proj, is_active=True):
                if env.id in existing_env_ids:
                    continue
                suggestions.append({
                    'project_id': proj.id,
                    'project_name': proj.name,
                    'environment_id': env.id,
                    'environment_name': env.name,
                    'reason': f'{proj.name} has no deployment on {cluster.name} '
                              f'for env {env.name} yet.',
                })
        return Response({
            'cluster_id': int(cluster_id),
            'suggestions': suggestions,
        })
