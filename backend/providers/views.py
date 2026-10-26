from Middlewares.rbac import Requires
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from .models import GitlabProject, Pipeline, Job, Deployment, ProviderIntegration
from .serializer import ProjectSerializer, PipelineSerializer, JobSerializer
from Utils.url_validator import validate_internal_url_no_metadata
from .utils import gitlab_retrieve_job_logs, gitlab_update_pipeline_status, extract_gitlab_info, trigger_pipeline_run, cancel_pipeline_run, get_gitlab_api_base
import json
from django.http import Http404, JsonResponse
import re
import requests
from rest_framework.permissions import IsAuthenticated
from rest_framework.permissions import AllowAny
from rest_framework.decorators import permission_classes, api_view
from django.conf import settings
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from Utils.elastic_search import get_elasticsearch_client, index_logs
from datetime import datetime
from Projects.models import ProjectService
import logging


logger = logging.getLogger(__name__)

schema_view = get_schema_view(
    openapi.Info(
        title="GitLab Log Retrieval API",
        default_version='v1',
        description="API for retrieving and managing GitLab logs",
        terms_of_service="https://www.yourapp.com/terms/",
        contact=openapi.Contact(email="contact@yourapp.com"),
        license=openapi.License(name="Your License"),
    ),
    public=True,
    permission_classes=(permissions.AllowAny,),  # Changed to AllowAny for easier testing
)

class ProjectList(APIView):
    # Viewers read; users and admins add projects.
    permission_classes = [IsAuthenticated, Requires(GET='project.read', POST='project.write')]

    @swagger_auto_schema(
        operation_description="Get a list of GitLab projects for the authenticated user's organization",
        responses={200: ProjectSerializer(many=True)}
    )
    def get(self, request):
        projects = GitlabProject.objects.filter(organisation=request.user.organisation)
        serializer = ProjectSerializer(projects, many=True)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Create a new GitLab project with verification",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['name', 'username', 'access_token'],
            properties={
                'gitlab_url': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project URL'),
                'username': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab username'),
                'access_token': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab access token'),
                'project_id': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project ID'),
            }
        ),
        responses={
            201: ProjectSerializer,
            400: "Bad Request",
            401: "Authentication with GitLab failed",
            404: "GitLab project not found"
        }
    )
    def post(self, request):
        data = request.data.copy()
        
        # Support Global Integrations - fetch credentials from ProviderIntegration if integration_id is provided
        integration_id = request.data.get('integration_id')
        if integration_id:
            try:
                from .models import ProviderIntegration
                integration = ProviderIntegration.objects.get(
                    pk=integration_id,
                    organisation=request.user.organisation,
                    provider_type='gitlab',
                    is_active=True
                )
                # Use credentials from the integration
                data['access_token'] = integration.credentials.get('token')
                data['gitlab_url'] = integration.base_url or 'https://gitlab.com'
            except ProviderIntegration.DoesNotExist:
                return Response({
                    'error': 'Integration not found or not accessible'
                }, status=status.HTTP_404_NOT_FOUND)
        
        gitlab_url = data.get('gitlab_url')
        
        # Only extract from URL if it contains a project path (has more than just domain)
        if gitlab_url and '/' in gitlab_url.replace('https://', '').replace('http://', ''):
            try:
                username, repository = extract_gitlab_info(gitlab_url)
                if username:
                    data['username'] = username
                if repository:
                    data['name'] = repository
            except Exception as e:
                logger.warning(f"Could not extract info from gitlab_url: {e}")
        
        # Verify GitLab project exists and is accessible before saving
        project_id = data.get('project_id')
        access_token = data.get('access_token')
        
        logger.info(f"GitLab project registration: project_id={project_id}, has_access_token={bool(access_token)}, gitlab_url={gitlab_url}")
        
        if not project_id or not access_token:
            return Response({
                'error': 'Project ID and access token are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Verify project with GitLab API
        gitlab_base = get_gitlab_api_base(url_hint=gitlab_url, project_id=project_id)
        gitlab_api_url = f"{gitlab_base}/api/v4/projects/{project_id}"
        headers = {"PRIVATE-TOKEN": access_token}
        
        try:
            # Verify project exists in GitLab
            response = requests.get(gitlab_api_url, headers=headers)
            
            if response.status_code == 401 or response.status_code == 403:
                logger.error(f"GitLab authentication failed for user {request.user}, project_id: {project_id}")
                return Response({
                    'error': 'Authentication failed. Invalid access token.'
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            elif response.status_code == 404:
                logger.error(f"GitLab project {project_id} not found or inaccessible for user {request.user}")
                return Response({
                    'error': f"Project with ID {project_id} does not exist or you don't have permission to access it"
                }, status=status.HTTP_404_NOT_FOUND)
                
            elif response.status_code != 200:
                return Response({
                    'error': f"GitLab API error: {response.status_code} - {response.text}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            # Project verification successful, now save the project
            project_data = response.json()
            
            # Update data with verified information from GitLab
            if not data.get('name'):
                data['name'] = project_data.get('name')
            if not data.get('username') and '/' in project_data.get('path_with_namespace', ''):
                data['username'] = project_data.get('path_with_namespace').split('/')[0]
            
            # Check if this GitLab project already exists
            existing_project = GitlabProject.objects.filter(project_id=project_id).first()
            if existing_project:
                # Project already exists - but check if webhook needs to be configured
                logger.info(f"GitLab project {project_id} already exists, reusing it")
                
                # If webhook is not configured, set it up now
                if not existing_project.webhook:
                    webhook_name = "Logs_webhook"
                    gitlab_webhook_url = f"{gitlab_base}/api/v4/projects/{project_id}/hooks"

                    # Try to find CICDBinding for binding-based URL + token
                    from Projects.models import CICDBinding as CICDBindingModel
                    cicd_binding = CICDBindingModel.objects.filter(
                        pipeline_id=str(project_id),
                        integration__provider_type='gitlab',
                        is_active=True,
                    ).first()

                    if cicd_binding and cicd_binding.webhook_secret:
                        url = f"{settings.SERVER_URL}/webhooks/gitlab/{cicd_binding.id}/"
                        token = cicd_binding.webhook_secret
                    else:
                        url = f"{settings.SERVER_URL}/webhooks/gitlab/"
                        token = None

                    gitlab_webhook_data = {
                        "url": url,
                        "push_events": True,
                        "merge_requests_events": False,
                        "tag_push_events": False,
                        "note_events": False,
                        "issue_events": False,
                        "confidential_issue_events": False,
                        "confidential_note_events": False,
                        "pipeline_events": True,
                        "wiki_page_events": False,
                        "deployment_events": False,
                        "job_events": True,
                        "name": webhook_name,
                    }
                    if token:
                        gitlab_webhook_data["token"] = token

                    try:
                        logger.info(f"Creating webhook for project {project_id} with URL: {url}")
                        webhook_response = requests.post(
                            gitlab_webhook_url,
                            headers=headers,
                            json=gitlab_webhook_data
                        )

                        if webhook_response.status_code == 201:
                            existing_project.webhook = True
                            existing_project.save()
                            if cicd_binding:
                                cicd_binding.webhook_configured = True
                                cicd_binding.webhook_id = str(webhook_response.json().get('id', ''))
                                cicd_binding.save(update_fields=['webhook_configured', 'webhook_id'])
                            logger.info(f"Webhook configured for existing GitLab project {project_id}")
                        else:
                            logger.warning(f"Failed to create webhook for existing project: status={webhook_response.status_code}, response={webhook_response.text}")
                    except Exception as e:
                        logger.error(f"Error creating webhook for existing project: {e}")
                
                return Response({
                    'success': True,
                    'project': {
                        'id': existing_project.id,
                        'name': existing_project.name,
                        'project_id': existing_project.project_id,
                    },
                    'message': 'Project already registered, linking to existing project'
                }, status=status.HTTP_200_OK)
            
            serializer = ProjectSerializer(data=data)
            if serializer.is_valid():
                project = serializer.save(organisation=request.user.organisation)
                
                # Removed Elasticsearch index creation - now related to project index name
                
                # Fetch initial pipelines for this project
                pipelines_url = f"{gitlab_base}/api/v4/projects/{project_id}/pipelines"
                pipelines_response = requests.get(pipelines_url, headers=headers)
                
                if pipelines_response.status_code == 200:
                    pipelines = pipelines_response.json()
                    
                    # Create pipelines in our database
                    for pipeline_data in pipelines:
                        Pipeline.objects.update_or_create(
                            project=project,
                            pipeline_id=str(pipeline_data['id']),
                            defaults={
                                'status': pipeline_data.get('status', 'unknown'),
                                'branch': pipeline_data.get('ref', 'unknown'),
                                'organisation': project.organisation  # Multi-tenancy isolation
                            }
                        )
                
                # Setup webhook automatically
                webhook_name = "Logs_webhook"
                gitlab_webhook_url = f"{gitlab_base}/api/v4/projects/{project_id}/hooks"

                # Try to find CICDBinding for binding-based URL + token
                from Projects.models import CICDBinding as CICDBindingNew
                cicd_binding_new = CICDBindingNew.objects.filter(
                    pipeline_id=str(project_id),
                    integration__provider_type='gitlab',
                    is_active=True,
                ).first()

                if cicd_binding_new and cicd_binding_new.webhook_secret:
                    url = f"{settings.SERVER_URL}/webhooks/gitlab/{cicd_binding_new.id}/"
                    token = cicd_binding_new.webhook_secret
                else:
                    url = f"{settings.SERVER_URL}/webhooks/gitlab/"
                    token = None

                gitlab_webhook_data = {
                    "url": url,
                    "push_events": True,  # Enabled for code changes tracking
                    "merge_requests_events": False,
                    "tag_push_events": False,
                    "note_events": False,
                    "issue_events": False,
                    "confidential_issue_events": False,
                    "confidential_note_events": False,
                    "pipeline_events": True,
                    "wiki_page_events": False,
                    "deployment_events": False,
                    "job_events": True,
                    "name": webhook_name,
                }
                if token:
                    gitlab_webhook_data["token"] = token

                webhook_response = requests.post(
                    gitlab_webhook_url,
                    headers=headers,
                    json=gitlab_webhook_data
                )

                if webhook_response.status_code == 201:
                    project.webhook = True
                    project.save()
                    if cicd_binding_new:
                        cicd_binding_new.webhook_configured = True
                        cicd_binding_new.webhook_id = str(webhook_response.json().get('id', ''))
                        cicd_binding_new.save(update_fields=['webhook_configured', 'webhook_id'])
                
                logger.warning(f"GitLab project creation attempted by user {request.user} for project_id: {project_id}")
                return Response({
                    'project': serializer.data,
                    'verification': 'Project successfully verified with GitLab',
                    'project_details': {
                        'id': project_data.get('id'),
                        'name': project_data.get('name'),
                        'web_url': project_data.get('web_url'),
                        'visibility': project_data.get('visibility')
                    },
                    'webhook_setup': project.webhook
                }, status=status.HTTP_201_CREATED)
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
                
        except requests.exceptions.RequestException as e:
            return Response({
                'error': f"Error connecting to GitLab API: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    

class ProjectDetail(APIView):
    # Viewers read; users and admins edit; only admins delete (see delete()).
    permission_classes = [IsAuthenticated, Requires(GET='project.read', PUT='project.write', DELETE='project.delete')]

    def get_object(self, pk):
        try:
            return GitlabProject.objects.get(pk=pk)
        except GitlabProject.DoesNotExist:
            raise Http404

    @swagger_auto_schema(
        operation_description="Get details of a specific GitLab project",
        manual_parameters=[
            openapi.Parameter('pk', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER)
        ],
        responses={
            200: ProjectSerializer,
            403: "Forbidden",
            404: "Not Found"
        }
    )
    def get(self, request, pk):
        project = self.get_object(pk)
        # Vérifier que l'utilisateur appartient à l'organisation du projet
        if project.organisation != request.user.organisation:
            return Response({"message": "You can not access to this Gitlab project "}, status=status.HTTP_403_FORBIDDEN)
        serializer = ProjectSerializer(project)
        return Response(serializer.data)

    @swagger_auto_schema(
        operation_description="Update a GitLab project",
        manual_parameters=[
            openapi.Parameter('pk', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER)
        ],
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                'gitlab_url': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project URL'),
                'name': openapi.Schema(type=openapi.TYPE_STRING, description='Project name'),
                'username': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab username'),
                'access_token': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab access token'),
                'project_id': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project ID'),
            }
        ),
        responses={
            200: ProjectSerializer,
            400: "Bad Request",
            403: "Forbidden",
            404: "Not Found"
        }
    )
    def put(self, request, pk):
        project = self.get_object(pk)
        
        # Vérifier que l'utilisateur appartient à l'organisation du projet
        if project.organisation != request.user.organisation:
            return Response({"message": "You can not access to this Gitlab project "}, status=status.HTTP_403_FORBIDDEN)
        data = request.data
        
        gitlab_url = data.get('gitlab_url')
        if gitlab_url:
            username, repository = extract_gitlab_info(gitlab_url)
            data['username'] = username
            data['name'] = repository
        
        serializer = ProjectSerializer(project, data=data)

        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @swagger_auto_schema(
        operation_description="Delete a GitLab project",
        manual_parameters=[
            openapi.Parameter('pk', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER)
        ],
        responses={
            204: "No Content",
            403: "Forbidden",
            404: "Not Found"
        }
    )
    def delete(self, request, pk):
        project = self.get_object(pk)
        # Vérifier que l'utilisateur appartient à l'organisation du projet
        if project.organisation != request.user.organisation:
            return Response({"message": "You can not access to this Gitlab project "}, status=status.HTTP_403_FORBIDDEN)
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)




class SetupGitLabWebhookView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    @swagger_auto_schema(
        operation_description="Setup GitLab webhook for a project",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['project_id'],
            properties={
                'project_id': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project ID'),
                'job_events': openapi.Schema(type=openapi.TYPE_BOOLEAN, description='Whether to listen for job events', default=True),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'message': openapi.Schema(type=openapi.TYPE_STRING, description='Success message')
                }
            ),
            500: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'message': openapi.Schema(type=openapi.TYPE_STRING, description='Error message'),
                    'github_response': openapi.Schema(type=openapi.TYPE_OBJECT, description='GitLab API response')
                }
            )
        }
    )
    def post(self, request):
        webhook_name = "Logs_webhook"
        job_events = request.data.get('job_events', True)
        project_id = request.data.get('project_id')

        # Only a project of the caller's own organisation: its stored token
        # must never act on behalf of another tenant.
        pr = GitlabProject.objects.filter(project_id=project_id, organisation=request.user.organisation).first()
        if not pr:
            logger.warning('No Project found')
            return Response({'message': 'No Project found'}, status=status.HTTP_404_NOT_FOUND)
        access_token=pr.get_access_token()
        gitlab_base = get_gitlab_api_base(project=pr)
        gitlab_api_url = f"{gitlab_base}/api/v4/projects/{project_id}/hooks"

        # Try to find a CICDBinding to use binding-based URL + token
        from Projects.models import CICDBinding
        cicd_binding = CICDBinding.objects.filter(
            pipeline_id=str(project_id),
            integration__provider_type='gitlab',
            is_active=True,
            project_service__project__organisation=request.user.organisation,
        ).first()

        if cicd_binding and cicd_binding.webhook_secret:
            url = f"{settings.SERVER_URL}/webhooks/gitlab/{cicd_binding.id}/"
            token = cicd_binding.webhook_secret
        else:
            # Legacy fallback — payload-based _resolve_binding will handle it
            url = f"{settings.SERVER_URL}/webhooks/gitlab/"
            token = None

        gitlab_data = {
            "url": url,
            "push_events": True,  # Enabled for code changes tracking
            "merge_requests_events": False,
            "tag_push_events": False,
            "note_events": False,
            "issue_events": False,
            "confidential_issue_events": False,
            "confidential_note_events": False,
            "pipeline_events": job_events,
            "wiki_page_events": False,
            "deployment_events": False,
            "job_events": job_events,
            "name": webhook_name,
        }
        if token:
            gitlab_data["token"] = token

        gitlab_headers = {
            "PRIVATE-TOKEN": access_token
        }
        gitlab_response = requests.post(gitlab_api_url, headers=gitlab_headers, json=gitlab_data)
        logger.debug(f'GitLab response: {gitlab_response.content}')
        if gitlab_response.status_code == 201:
            pr.webhook=True
            pr.save()
            if cicd_binding:
                cicd_binding.webhook_configured = True
                cicd_binding.webhook_id = str(gitlab_response.json().get('id', ''))
                cicd_binding.save(update_fields=['webhook_configured', 'webhook_id'])
            logger.debug('Webhook verified OK')
            return Response({"message": "webhook set for this Gitlab project"})
        else :
            logger.debug('Webhook verification failed')
            # GitLab's raw error body stays in the log, not in the response.
            logger.warning('GitLab webhook setup failed: HTTP %s', gitlab_response.status_code)
            return Response({"message": "Error, webhook is not set for this GitLab project",
                             "gitlab_status": gitlab_response.status_code}, status=502)


class DeleteGitLabWebhookView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    @swagger_auto_schema(
        operation_description="Delete GitLab webhook for a project",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['project_id'],
            properties={
                'project_id': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project ID'),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'message': openapi.Schema(type=openapi.TYPE_STRING, description='Success message'),
                    'deleted_webhooks': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(type=openapi.TYPE_STRING),
                        description='List of deleted webhook URLs'
                    )
                }
            )
        }
    )
    def post(self, request):
        project_id = request.data.get('project_id')
        pr = GitlabProject.objects.filter(project_id=project_id, organisation=request.user.organisation).first()
        if not pr:
            return Response({'message': 'No Project found'}, status=status.HTTP_404_NOT_FOUND)
        access_token=pr.get_access_token()
        gitlab_base = get_gitlab_api_base(project=pr)
        # List all webhooks
        response = requests.get(
            f"{gitlab_base}/api/v4/projects/{project_id}/hooks",
            headers={"PRIVATE-TOKEN": access_token}
        )
        webhooks = response.json()

        # Find and delete webhooks with URLs ending with 'api/gitlab/webhook'
        deleted_webhooks = []
        for webhook in webhooks:
            if webhook["url"].endswith("api/gitlab/webhook/"):
                response = requests.delete(
                    f"{gitlab_base}/api/v4/projects/{project_id}/hooks/{webhook['id']}",
                    headers={"PRIVATE-TOKEN": access_token}
                )
                if response.status_code == 204:
                    deleted_webhooks.append(webhook["url"])

        if deleted_webhooks:
            pr.webhook=False
            pr.save()
            return Response({'message': 'Webhooks deleted successfully.', 'deleted_webhooks': deleted_webhooks})
        else:
            return Response({'message': 'No webhooks found to delete.'})





_GITLAB_PIPELINE_FIELDS = ('id', 'iid', 'status', 'ref', 'sha', 'source', 'web_url', 'created_at', 'updated_at')


def _gitlab_project_ref(project_id):
    """GitLab's id for a project in a URL path: a number, or the
    ``group/project`` path encoded as one segment. None when it is not one,
    so it can never reach another path of the server."""
    from urllib.parse import quote, unquote
    raw = unquote(str(project_id or '')).strip()
    if not raw or len(raw) > 255 or any(seg in ('', '.', '..') for seg in raw.split('/')):
        return None
    return quote(raw, safe='')


class VerifyGitLabProjectView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    @swagger_auto_schema(
        operation_description="Verify if a GitLab project exists and is accessible, and fetch its pipelines",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['project_id', 'access_token'],
            properties={
                'project_id': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab project ID'),
                'access_token': openapi.Schema(type=openapi.TYPE_STRING, description='GitLab access token'),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'exists': openapi.Schema(type=openapi.TYPE_BOOLEAN, description='Whether the project exists'),
                    'project_details': openapi.Schema(
                        type=openapi.TYPE_OBJECT, 
                        properties={
                            'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                            'name': openapi.Schema(type=openapi.TYPE_STRING),
                            'web_url': openapi.Schema(type=openapi.TYPE_STRING),
                            'visibility': openapi.Schema(type=openapi.TYPE_STRING),
                        },
                        description='Project details (if exists)'
                    ),
                    'pipelines': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'status': openapi.Schema(type=openapi.TYPE_STRING),
                                'ref': openapi.Schema(type=openapi.TYPE_STRING),
                                'sha': openapi.Schema(type=openapi.TYPE_STRING),
                                'created_at': openapi.Schema(type=openapi.TYPE_STRING),
                                'updated_at': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        ),
                        description='List of pipelines for the project'
                    )
                }
            ),
            401: "Authentication failed",
            404: "Project not found"
        }
    )
    def post(self, request):
        project_id = request.data.get('project_id')
        access_token = request.data.get('access_token')

        if not project_id or not access_token:
            return Response({
                'exists': False,
                'error': 'Project ID and access token are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # The caller chooses the GitLab server: only its /api/v4/projects/<id>
        # routes are called, without following redirects, never a cloud
        # metadata address, and GitLab's raw replies aren't echoed back.
        # Private addresses stay allowed: self-hosted GitLab is often internal.
        project_ref = _gitlab_project_ref(project_id)
        if project_ref is None:
            return Response({'exists': False, 'error': 'Invalid project ID'}, status=status.HTTP_400_BAD_REQUEST)
        gitlab_url = request.data.get('gitlab_url')
        if gitlab_url:
            try:
                validate_internal_url_no_metadata(gitlab_url)
            except ValueError as e:
                return Response({'exists': False, 'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
            gitlab_base = get_gitlab_api_base(url_hint=gitlab_url)
        else:
            known = GitlabProject.objects.filter(project_id=str(project_id),
                                                 organisation=request.user.organisation).first()
            gitlab_base = get_gitlab_api_base(project=known)
        gitlab_api_url = f"{gitlab_base}/api/v4/projects/{project_ref}"
        headers = {"PRIVATE-TOKEN": access_token}
        fetch = dict(headers=headers, timeout=30, allow_redirects=False)

        try:
            response = requests.get(gitlab_api_url, **fetch)

            if response.status_code == 200:
                project_data = response.json()
                if not isinstance(project_data, dict):
                    return Response({'exists': False, 'error': 'Not a GitLab project'},
                                    status=status.HTTP_502_BAD_GATEWAY)

                pipelines_response = requests.get(f"{gitlab_api_url}/pipelines", **fetch)
                pipelines = []
                if pipelines_response.status_code == 200 and isinstance(pipelines_response.json(), list):
                    pipelines = [{k: p.get(k) for k in _GITLAB_PIPELINE_FIELDS}
                                 for p in pipelines_response.json() if isinstance(p, dict)]
                    # Stored only on the caller's own organisation's project.
                    project_obj = GitlabProject.objects.filter(
                        project_id=str(project_id), organisation=request.user.organisation).first()
                    if project_obj:
                        for pipeline_data in pipelines:
                            if pipeline_data.get('id') is None:
                                continue
                            Pipeline.objects.update_or_create(
                                project=project_obj,
                                pipeline_id=str(pipeline_data['id']),
                                defaults={
                                    'status': pipeline_data.get('status') or 'unknown',
                                    'branch': pipeline_data.get('ref') or 'unknown',
                                    'organisation': project_obj.organisation,
                                }
                            )

                return Response({
                    'exists': True,
                    'project_details': {
                        'id': project_data.get('id'),
                        'name': project_data.get('name'),
                        'web_url': project_data.get('web_url'),
                        'visibility': project_data.get('visibility'),
                        'default_branch': project_data.get('default_branch'),
                        'description': project_data.get('description'),
                    },
                    'pipelines': pipelines
                })
            elif response.status_code == 401 or response.status_code == 403:
                return Response({
                    'exists': False,
                    'error': 'Authentication failed. Invalid access token.'
                }, status=status.HTTP_401_UNAUTHORIZED)
            elif response.status_code == 404:
                return Response({
                    'exists': False,
                    'error': f"Project with ID {project_id} does not exist or you don't have permission to access it"
                }, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({
                    'exists': False,
                    'error': f"GitLab API error: HTTP {response.status_code}"
                }, status=status.HTTP_502_BAD_GATEWAY)

        except (requests.exceptions.RequestException, ValueError) as e:
            logger.warning("GitLab project verification failed: %s", e)
            return Response({
                'exists': False,
                'error': 'Could not reach the GitLab API'
            }, status=status.HTTP_502_BAD_GATEWAY)



class PipelineLogsView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='batch.read')]
    @swagger_auto_schema(
        operation_description="Get all logs for jobs in a specific pipeline",
        manual_parameters=[
            openapi.Parameter('project_id', openapi.IN_PATH, description="Project ID", type=openapi.TYPE_INTEGER),
            openapi.Parameter('pipeline_id', openapi.IN_PATH, description="Pipeline ID", type=openapi.TYPE_INTEGER)
        ],
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'jobs': openapi.Schema(
                        type=openapi.TYPE_ARRAY,
                        items=openapi.Schema(
                            type=openapi.TYPE_OBJECT,
                            properties={
                                'id': openapi.Schema(type=openapi.TYPE_INTEGER),
                                'name': openapi.Schema(type=openapi.TYPE_STRING),
                                'status': openapi.Schema(type=openapi.TYPE_STRING),
                                'logs': openapi.Schema(type=openapi.TYPE_STRING),
                            }
                        )
                    )
                }
            ),
            403: "Forbidden",
            404: "Project or pipeline not found"
        }
    )
    def get(self, request, project_id, pipeline_id):
        try:
            # Get the project and verify access permissions
            project = GitlabProject.objects.get(pk=project_id)
            if project.organisation != request.user.organisation:
                return Response({"message": "You cannot access this GitLab project"}, 
                              status=status.HTTP_403_FORBIDDEN)
            
            # Get the pipeline
            pipeline = Pipeline.objects.get(pk=pipeline_id, project=project)
            
            # Get the GitLab project ID and token
            gitlab_project_id = project.project_id
            access_token = project.get_access_token()
            
            # Get the pipeline jobs from GitLab API
            gitlab_base = get_gitlab_api_base(project=project)
            gitlab_api_url = f"{gitlab_base}/api/v4/projects/{gitlab_project_id}/pipelines/{pipeline.pipeline_id}/jobs"
            headers = {"PRIVATE-TOKEN": access_token}
            
            response = requests.get(gitlab_api_url, headers=headers)
            
            if response.status_code != 200:
                return Response({
                    "message": f"Failed to fetch jobs from GitLab: {response.text}"
                }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
            jobs_data = response.json()
            jobs_with_logs = []
            
            # For each job, fetch its logs
            for job in jobs_data:
                job_id = job['id']
                job_name = job['name']
                job_status = job['status']

                if job_status != "failed":
                    continue  # Only process failed jobs

                logs_url = f"{gitlab_base}/api/v4/projects/{gitlab_project_id}/jobs/{job_id}/trace"
                logs_response = requests.get(logs_url, headers=headers)
                logs = ""
                if logs_response.status_code == 200:
                    logs = logs_response.text
                else:
                    logs = f"Unable to retrieve logs: {logs_response.status_code} - {logs_response.reason}"

                job_with_logs = {
                    'id': job_id,
                    'name': job_name,
                    'status': job_status,
                    'logs': logs
                }
                jobs_with_logs.append(job_with_logs)

                Job.objects.update_or_create(
                    pipeline=pipeline,
                    job_id=str(job_id),
                    defaults={
                        'name': job_name,
                        'status': job_status,
                    }
                )

            return Response({"jobs": jobs_with_logs})
        except GitlabProject.DoesNotExist:
            return Response({"message": "Project not found"}, status=status.HTTP_404_NOT_FOUND)
        except Pipeline.DoesNotExist:
            return Response({"message": "Pipeline not found"}, status=status.HTTP_404_NOT_FOUND)
        except Exception as e:
            return Response({
                "message": f"Error retrieving pipeline logs: {str(e)}"
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VerifyGitHubProjectView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    """
    Verify a GitHub repository exists and the provided token has access.
    
    Uses the GitHub API to check repository access.
    """
    
    @swagger_auto_schema(
        operation_description="Verify if a GitHub repository exists and is accessible",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['github_repo', 'github_token'],
            properties={
                'github_repo': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='GitHub repository in owner/repo format'
                ),
                'github_token': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='GitHub Personal Access Token'
                ),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'exists': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    'name': openapi.Schema(type=openapi.TYPE_STRING),
                    'full_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'description': openapi.Schema(type=openapi.TYPE_STRING),
                    'private': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    'html_url': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            400: "Bad request - missing parameters",
            401: "Authentication failed - invalid token",
            404: "Repository not found"
        }
    )
    def post(self, request):
        github_repo = request.data.get('github_repo')
        github_token = request.data.get('github_token')

        if not github_repo or not github_token:
            return Response({
                'exists': False,
                'error': 'Repository path (owner/repo) and access token are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate repo format
        if '/' not in github_repo:
            return Response({
                'exists': False,
                'error': 'Repository must be in owner/repo format (e.g., microsoft/vscode)'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Build GitHub API URL
        github_api_url = f"https://api.github.com/repos/{github_repo}"
        
        headers = {
            "Authorization": f"Bearer {github_token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
        
        try:
            # Try to get repository details from GitHub
            response = requests.get(github_api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                repo_data = response.json()
                
                return Response({
                    'exists': True,
                    'name': repo_data.get('name'),
                    'full_name': repo_data.get('full_name'),
                    'description': repo_data.get('description'),
                    'private': repo_data.get('private'),
                    'html_url': repo_data.get('html_url'),
                    'default_branch': repo_data.get('default_branch'),
                    'language': repo_data.get('language'),
                }, status=status.HTTP_200_OK)
                
            elif response.status_code == 401:
                return Response({
                    'exists': False,
                    'error': 'Invalid or expired GitHub token. Please check your Personal Access Token.'
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            elif response.status_code == 403:
                # Rate limiting or scope issue
                error_msg = 'Access denied. Token may lack required scopes (repo).'
                if 'X-RateLimit-Remaining' in response.headers:
                    if response.headers['X-RateLimit-Remaining'] == '0':
                        error_msg = 'GitHub API rate limit exceeded. Please wait and try again.'
                return Response({
                    'exists': False,
                    'error': error_msg
                }, status=status.HTTP_403_FORBIDDEN)
                
            elif response.status_code == 404:
                return Response({
                    'exists': False,
                    'error': f'Repository "{github_repo}" not found. Check the repository path.'
                }, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({
                    'exists': False,
                    'error': f'GitHub API returned status {response.status_code}'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except requests.exceptions.Timeout:
            return Response({
                'exists': False,
                'error': 'Request to GitHub timed out. Please try again.'
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
            
        except requests.exceptions.RequestException as e:
            return Response({
                'exists': False,
                'error': f'Network error while connecting to GitHub: {str(e)}'
            }, status=status.HTTP_502_BAD_GATEWAY)
            
        except Exception as e:
            return Response({
                'exists': False,
                'error': f'Error verifying GitHub repository: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VerifyBitbucketProjectView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    """
    Verify a Bitbucket repository exists and the provided OAuth2 token has access.
    
    Uses the Bitbucket Cloud API to check repository access.
    """
    
    @swagger_auto_schema(
        operation_description="Verify if a Bitbucket repository exists and is accessible",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['bitbucket_repo', 'bitbucket_token'],
            properties={
                'bitbucket_repo': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='Bitbucket repository in workspace/repo format'
                ),
                'bitbucket_token': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='Bitbucket OAuth2 access token'
                ),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'exists': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    'name': openapi.Schema(type=openapi.TYPE_STRING),
                    'full_name': openapi.Schema(type=openapi.TYPE_STRING),
                    'description': openapi.Schema(type=openapi.TYPE_STRING),
                    'is_private': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                }
            ),
            400: "Bad request - missing parameters",
            401: "Authentication failed - invalid token",
            404: "Repository not found"
        }
    )
    def post(self, request):
        bitbucket_repo = request.data.get('bitbucket_repo')
        bitbucket_token = request.data.get('bitbucket_token')

        if not bitbucket_repo or not bitbucket_token:
            return Response({
                'exists': False,
                'error': 'Repository path (workspace/repo) and access token are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Validate repo format
        if '/' not in bitbucket_repo:
            return Response({
                'exists': False,
                'error': 'Repository must be in workspace/repo format (e.g., atlassian/bitbucket)'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Build Bitbucket API URL
        bitbucket_api_url = f"https://api.bitbucket.org/2.0/repositories/{bitbucket_repo}"
        
        headers = {
            "Authorization": f"Bearer {bitbucket_token}",
            "Accept": "application/json"
        }
        
        try:
            # Try to get repository details from Bitbucket
            response = requests.get(bitbucket_api_url, headers=headers, timeout=30)
            
            if response.status_code == 200:
                repo_data = response.json()
                
                return Response({
                    'exists': True,
                    'name': repo_data.get('name'),
                    'full_name': repo_data.get('full_name'),
                    'description': repo_data.get('description'),
                    'is_private': repo_data.get('is_private'),
                    'uuid': repo_data.get('uuid'),
                    'language': repo_data.get('language'),
                    'mainbranch': repo_data.get('mainbranch', {}).get('name'),
                }, status=status.HTTP_200_OK)
                
            elif response.status_code == 401:
                return Response({
                    'exists': False,
                    'error': 'Invalid or expired OAuth2 token. Please re-authenticate with Bitbucket.'
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            elif response.status_code == 403:
                return Response({
                    'exists': False,
                    'error': 'Access denied. Token may lack required scopes (repository:read).'
                }, status=status.HTTP_403_FORBIDDEN)
                
            elif response.status_code == 404:
                return Response({
                    'exists': False,
                    'error': f'Repository "{bitbucket_repo}" not found. Check workspace and repo name.'
                }, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({
                    'exists': False,
                    'error': f'Bitbucket API returned status {response.status_code}'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except requests.exceptions.Timeout:
            return Response({
                'exists': False,
                'error': 'Request to Bitbucket timed out. Please try again.'
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
            
        except requests.exceptions.RequestException as e:
            return Response({
                'exists': False,
                'error': f'Network error while connecting to Bitbucket: {str(e)}'
            }, status=status.HTTP_502_BAD_GATEWAY)
            
        except Exception as e:
            return Response({
                'exists': False,
                'error': f'Error verifying Bitbucket repository: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class VerifyAzureDevOpsProjectView(APIView):
    permission_classes = [IsAuthenticated, Requires(POST='project.write')]

    """
    Verify an Azure DevOps project exists and the provided PAT has access.
    
    Uses the Azure DevOps REST API to check project access.
    """
    
    @swagger_auto_schema(
        operation_description="Verify if an Azure DevOps project exists and is accessible",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            required=['organization', 'project', 'pat'],
            properties={
                'organization': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='Azure DevOps organization name'
                ),
                'project': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='Azure DevOps project name or ID'
                ),
                'pat': openapi.Schema(
                    type=openapi.TYPE_STRING, 
                    description='Personal Access Token with Build/Release read scope'
                ),
            }
        ),
        responses={
            200: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    'exists': openapi.Schema(type=openapi.TYPE_BOOLEAN),
                    'name': openapi.Schema(type=openapi.TYPE_STRING),
                    'description': openapi.Schema(type=openapi.TYPE_STRING),
                    'state': openapi.Schema(type=openapi.TYPE_STRING),
                }
            ),
            400: "Bad request - missing parameters",
            401: "Authentication failed - invalid PAT",
            404: "Project not found"
        }
    )
    def post(self, request):
        organization = request.data.get('organization')
        project = request.data.get('project')
        pat = request.data.get('pat')

        if not organization or not project or not pat:
            return Response({
                'exists': False,
                'error': 'Organization, project name, and PAT are required'
            }, status=status.HTTP_400_BAD_REQUEST)

        # Build Azure DevOps API URL
        # Format: https://dev.azure.com/{org}/_apis/projects/{project}?api-version=7.1
        azure_api_url = f"https://dev.azure.com/{organization}/_apis/projects/{project}"
        
        # Azure DevOps uses Basic Auth with PAT (username is empty)
        import base64
        auth_string = base64.b64encode(f":{pat}".encode()).decode()
        
        headers = {
            "Authorization": f"Basic {auth_string}",
            "Accept": "application/json"
        }
        
        params = {"api-version": "7.1"}
        
        try:
            # Try to get project details from Azure DevOps
            response = requests.get(azure_api_url, headers=headers, params=params, timeout=30)
            
            if response.status_code == 200:
                project_data = response.json()
                
                return Response({
                    'exists': True,
                    'id': project_data.get('id'),
                    'name': project_data.get('name'),
                    'description': project_data.get('description'),
                    'state': project_data.get('state'),
                    'visibility': project_data.get('visibility'),
                    'url': project_data.get('url'),
                }, status=status.HTTP_200_OK)
                
            elif response.status_code == 401:
                return Response({
                    'exists': False,
                    'error': 'Invalid or expired PAT. Please check your Personal Access Token.'
                }, status=status.HTTP_401_UNAUTHORIZED)
                
            elif response.status_code == 403:
                return Response({
                    'exists': False,
                    'error': 'Access denied. PAT may lack required scopes (Build: Read, Release: Read).'
                }, status=status.HTTP_403_FORBIDDEN)
                
            elif response.status_code == 404:
                return Response({
                    'exists': False,
                    'error': f'Project "{project}" not found in organization "{organization}".'
                }, status=status.HTTP_404_NOT_FOUND)
            else:
                return Response({
                    'exists': False,
                    'error': f'Azure DevOps API returned status {response.status_code}'
                }, status=status.HTTP_400_BAD_REQUEST)
                
        except requests.exceptions.Timeout:
            return Response({
                'exists': False,
                'error': 'Request to Azure DevOps timed out. Please try again.'
            }, status=status.HTTP_504_GATEWAY_TIMEOUT)
            
        except requests.exceptions.RequestException as e:
            return Response({
                'exists': False,
                'error': f'Network error while connecting to Azure DevOps: {str(e)}'
            }, status=status.HTTP_502_BAD_GATEWAY)
            
        except Exception as e:
            return Response({
                'exists': False,
                'error': f'Error verifying Azure DevOps project: {str(e)}'
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
from rest_framework import viewsets, serializers
from rest_framework.decorators import action
from django.db.models import Count, Q
from django.utils.decorators import method_decorator
from django.views.decorators.cache import cache_page
from .models import ProviderIntegration
from .serializers import (
    ProviderIntegrationSerializer,
    ProviderIntegrationListSerializer,
    VerifyIntegrationSerializer,
    DiscoveredRepoSerializer,
)

# ── Static provider catalogue (computed once at import time) ─────
_PROVIDER_TYPE_CACHE = None

def _get_provider_types():
    """Compute provider types list once and cache at module level."""
    global _PROVIDER_TYPE_CACHE
    if _PROVIDER_TYPE_CACHE is None:
        result = []
        for code, display_name in ProviderIntegration.PROVIDER_TYPES:
            temp = ProviderIntegration(provider_type=code)
            result.append({
                'code': code,
                'name': display_name,
                'capabilities': temp.get_default_capabilities(),
                'default_url': temp.display_url,
            })
        _PROVIDER_TYPE_CACHE = result
    return _PROVIDER_TYPE_CACHE


class ProviderIntegrationViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Global Provider Integrations.

    Endpoints:
    - GET    /api/providers/integrations/                — List all integrations for org
    - POST   /api/providers/integrations/                — Create new integration
    - GET    /api/providers/integrations/{id}/            — Get integration details
    - PUT    /api/providers/integrations/{id}/            — Update integration
    - DELETE /api/providers/integrations/{id}/            — Delete integration
    - POST   /api/providers/integrations/{id}/verify/     — Test connection
    - GET    /api/providers/integrations/{id}/repos/      — Auto-discover repos
    - POST   /api/providers/integrations/{id}/health-check/ — Check single health
    - GET    /api/providers/integrations/health-check-all/  — Check all (parallel)
    - GET    /api/providers/integrations/{id}/usage/      — Per-integration usage
    - GET    /api/providers/integrations/usage-summary/   — Batch usage (eliminates N+1)
    - POST   /api/providers/integrations/{id}/sync/       — Sync/refresh
    - GET    /api/providers/integrations/provider-types/  — Static catalogue (cached)

    Multi-tenancy: All queries are scoped to user's organisation.
    """
    serializer_class = ProviderIntegrationSerializer
    permission_classes = [IsAuthenticated, Requires(GET='integration.read', POST='integration.use', create='integration.manage', update='integration.manage', partial_update='integration.manage', destroy='integration.manage', test_connection='integration.manage')]

    def get_queryset(self):
        """Filter integrations by user's organisation."""
        if hasattr(self.request, 'user') and hasattr(self.request.user, 'organisation'):
            return ProviderIntegration.objects.filter(
                organisation=self.request.user.organisation
            ).select_related('organisation', 'created_by')
        return ProviderIntegration.objects.none()

    def get_serializer_class(self):
        """Use lightweight serializer for list action."""
        if self.action == 'list':
            return ProviderIntegrationListSerializer
        return ProviderIntegrationSerializer

    def perform_create(self, serializer):
        """Automatically set organisation and created_by."""
        if hasattr(self.request.user, 'organisation'):
            extra = {}
            if serializer.validated_data.get('provider_type') in ProviderIntegration.GITOPS_PROVIDERS:
                extra = {'category': 'gitops', 'verification_status': 'verified'}
            serializer.save(
                organisation=self.request.user.organisation,
                created_by=self.request.user,
                **extra,
            )
        else:
            raise serializers.ValidationError("User must belong to an organisation")

    # ── verify ───────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='verify')
    def verify(self, request, pk=None):
        """
        Test connection to the provider.

        Returns 200 on success, 400 on failure.
        """
        integration = self.get_object()

        # Demo-seeded rows carry the sentinel placeholder credential.
        # The base_url points at a fabricated hostname, so calling the
        # real provider would just error. Report a synthetic OK
        # instead — visitors get the "verified" UX without the demo
        # box hammering non-existent endpoints.
        _DEMO_PLACEHOLDER = 'SEED_DEMO_PLACEHOLDER_NOT_A_REAL_SECRET'
        if integration.get_access_token() == _DEMO_PLACEHOLDER:
            integration.mark_verified(success=True)
            return Response({
                'success': True,
                'message': 'OK (demo)',
                'user_info': {'demo': True, 'note': 'seeded record'},
            })

        if integration.provider_type in ProviderIntegration.GITOPS_PROVIDERS:
            # Nothing to connect to: the controller sends events to SerOps.
            integration.mark_verified(success=True)
            return Response({
                'success': True,
                'message': f'{integration.get_provider_type_display()} sends deployments to SerOps; '
                           'bind a service to get its webhook URL.',
                'user_info': {},
            })

        try:
            from .scm_providers import (
                get_provider, get_cicd_provider,
                SCMProviderError, CICD_PROVIDERS,
            )

            if integration.provider_type in CICD_PROVIDERS:
                creds = integration.get_credentials()
                provider = get_cicd_provider(
                    provider_name=integration.provider_type,
                    base_url=integration.base_url or '',
                    username=creds.get('username', ''),
                    api_token=integration.get_access_token(),
                )
            else:
                provider = get_provider(
                    provider_name=integration.provider_type,
                    project_id='',
                    access_token=integration.get_access_token(),
                    base_url=integration.base_url,
                    organization=integration.provider_organization(),
                )

            result = provider.verify_connection()
            integration.mark_verified(success=True)
            return Response({
                'success': True,
                'message': 'Connection verified successfully',
                'user_info': result,
            })

        except SCMProviderError as e:
            integration.mark_verified(success=False, error=str(e))
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Integration verification failed: %s", e)
            integration.mark_verified(success=False, error=str(e))
            return Response(
                {'success': False, 'message': f'Verification failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # ── test (pre-save connection test) ──────────────────────────

    @action(detail=False, methods=['post'], url_path='test')
    def test_connection(self, request):
        """
        Test provider credentials without creating an integration.

        Allows users to verify their credentials before saving.
        """
        provider_type = request.data.get('provider_type')
        base_url = request.data.get('base_url')
        access_token = request.data.get('access_token')
        credentials = request.data.get('credentials', {})

        if not provider_type:
            return Response(
                {'success': False, 'message': 'Provider type is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if provider_type in ProviderIntegration.GITOPS_PROVIDERS:
            return Response({
                'success': True,
                'message': 'Nothing to connect to: the controller sends deployments to SerOps.',
                'user_info': {},
            })
        if not access_token:
            return Response(
                {'success': False, 'message': 'Access token is required'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            from .scm_providers import (
                get_provider, get_cicd_provider,
                SCMProviderError, CICD_PROVIDERS,
            )

            if provider_type in CICD_PROVIDERS:
                provider = get_cicd_provider(
                    provider_name=provider_type,
                    base_url=base_url or '',
                    username=credentials.get('username', ''),
                    api_token=access_token,
                )
            else:
                provider = get_provider(
                    provider_name=provider_type,
                    project_id='',
                    access_token=access_token,
                    base_url=base_url,
                    organization=(credentials or {}).get('organization') or request.data.get('organization'),
                )

            result = provider.verify_connection()
            return Response({
                'success': True,
                'message': 'Connection verified successfully',
                'user_info': result,
            })

        except SCMProviderError as e:
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Test connection failed: %s", e)
            return Response(
                {'success': False, 'message': f'Connection test failed: {str(e)}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

    # ── repos (with hard timeout) ────────────────────────────────

    @action(detail=True, methods=['get'], url_path='repos')
    def repos(self, request, pk=None):
        """
        Discover repositories from the provider.

        Query params:
            page (int): Page number (default: 1)
            per_page (int): Items per page (default: 20, max: 100)
            search (str): Optional search term

        Uses a hard 10-second timeout to prevent slow providers from
        blocking the Django worker thread.
        """
        integration = self.get_object()

        if not integration.is_verified:
            return Response(
                {
                    'error': 'Integration must be verified before discovering repos',
                    'verification_status': integration.verification_status,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        page = int(request.query_params.get('page', 1))
        per_page = min(int(request.query_params.get('per_page', 20)), 100)
        search = request.query_params.get('search', '')

        try:
            from .scm_providers import get_provider, SCMProviderError
            from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

            provider = get_provider(
                provider_name=integration.provider_type,
                project_id='',
                access_token=integration.get_access_token(),
                base_url=integration.base_url,
                organization=integration.provider_organization(),
            )

            # Hard 10s timeout to protect worker pool
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    provider.list_projects,
                    page=page,
                    per_page=per_page,
                    search=search,
                )
                repos = future.result(timeout=10)

            serializer = DiscoveredRepoSerializer(repos, many=True)
            return Response({
                'results': serializer.data,
                'page': page,
                'per_page': per_page,
                'total': len(repos),
            })

        except FuturesTimeout:
            return Response(
                {'error': 'Repository discovery timed out after 10 seconds. Try again or narrow your search.'},
                status=status.HTTP_504_GATEWAY_TIMEOUT,
            )
        except SCMProviderError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Failed to discover repos: %s", e)
            return Response(
                {'error': f'Failed to discover repositories: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── provider-types (cached, static data) ─────────────────────

    @action(detail=False, methods=['get'], url_path='provider-types')
    def provider_types(self, request):
        """
        Get available provider types and their capabilities.

        Response is computed once at module load and served from memory.
        """
        return Response(_get_provider_types())

    # ── health-check (single integration) ────────────────────────

    @action(detail=True, methods=['post'], url_path='health-check')
    def health_check(self, request, pk=None):
        """
        Check health of a specific integration.

        Verifies connection is still valid and measures latency.
        """
        integration = self.get_object()
        try:
            from .services import IntegrationHealthService
            health = IntegrationHealthService(integration).check_health()
            if health['healthy']:
                return Response(health)
            return Response(health, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.exception("Health check failed: %s", e)
            return Response(
                {'healthy': False, 'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── health-check-all (parallel fan-out) ──────────────────────

    @action(detail=False, methods=['get'], url_path='health-check-all')
    def health_check_all(self, request):
        """
        Check health of all integrations for the user's org **in parallel**.

        Uses ThreadPoolExecutor to fan out external API calls so that N
        integrations complete in ~max(latency) instead of sum(latency).
        """
        try:
            from .services import IntegrationHealthService

            results = IntegrationHealthService.check_all_for_org(
                request.user.organisation
            )
            healthy_count = sum(1 for r in results if r['healthy'])
            return Response({
                'total': len(results),
                'healthy': healthy_count,
                'unhealthy': len(results) - healthy_count,
                'results': results,
            })
        except Exception as e:
            logger.exception("Health check all failed: %s", e)
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    # ── usage (single integration, DB-limited) ───────────────────

    @action(detail=True, methods=['get'], url_path='usage')
    def usage(self, request, pk=None):
        """
        Get usage statistics for a single integration.

        Returns the count and first 10 services using this integration.
        Uses DB-level LIMIT instead of fetching all rows.
        """
        integration = self.get_object()
        try:
            from Projects.models import SCMBinding, CICDBinding

            # DB-level limit: only fetch first 10 rows per binding type
            scm_bindings = (
                SCMBinding.objects
                .filter(integration=integration)
                .select_related('service', 'service__project')[:10]
            )
            cicd_bindings = (
                CICDBinding.objects
                .filter(integration=integration)
                .select_related('service', 'service__project')[:10]
            )

            service_ids = set()
            services_list = []

            for binding in scm_bindings:
                if binding.service_id not in service_ids:
                    service_ids.add(binding.service_id)
                    services_list.append({
                        'id': binding.service.id,
                        'name': binding.service.name,
                        'project': (
                            binding.service.project.name
                            if binding.service.project else None
                        ),
                        'binding_type': 'scm',
                    })

            for binding in cicd_bindings:
                if binding.service_id not in service_ids:
                    service_ids.add(binding.service_id)
                    services_list.append({
                        'id': binding.service.id,
                        'name': binding.service.name,
                        'project': (
                            binding.service.project.name
                            if binding.service.project else None
                        ),
                        'binding_type': 'cicd',
                    })

            return Response({
                'services_count': len(services_list),
                'services': services_list[:10],
                'last_sync': (
                    integration.last_verified_at.isoformat()
                    if integration.last_verified_at else None
                ),
                'integration_id': integration.id,
                'integration_name': integration.name,
            })

        except Exception as e:
            logger.exception("Failed to get integration usage: %s", e)
            return Response({
                'services_count': 0,
                'services': [],
                'last_sync': None,
                'error': str(e),
            })

    # ── usage-summary (batch — eliminates frontend N+1) ──────────

    @action(detail=False, methods=['get'], url_path='usage-summary')
    def usage_summary(self, request):
        """
        Batch endpoint returning service counts for **all** integrations
        in the user's org in a single SQL query.

        Replaces the frontend pattern of fetching /usage/ per integration.

        Response:
            {
              "<integration_id>": {
                "services_count": 3,
                "last_sync": "2026-02-14T..."
              },
              ...
            }
        """
        org = getattr(request.user, 'organisation', None)
        if not org:
            return Response({})

        try:
            from Projects.models import SCMBinding, CICDBinding

            # Annotated counts — one query per binding type
            scm_counts = dict(
                SCMBinding.objects
                .filter(integration__organisation=org)
                .values_list('integration_id')
                .annotate(cnt=Count('id', distinct=True))
                .values_list('integration_id', 'cnt')
            )
            cicd_counts = dict(
                CICDBinding.objects
                .filter(integration__organisation=org)
                .values_list('integration_id')
                .annotate(cnt=Count('id', distinct=True))
                .values_list('integration_id', 'cnt')
            )

            # Merge counts + last_verified_at from the integrations
            integrations = ProviderIntegration.objects.filter(
                organisation=org,
            ).values('id', 'last_verified_at')

            summary = {}
            for integ in integrations:
                integ_id = integ['id']
                scm_n = scm_counts.get(integ_id, 0)
                cicd_n = cicd_counts.get(integ_id, 0)
                last_sync = integ['last_verified_at']
                summary[str(integ_id)] = {
                    'services_count': scm_n + cicd_n,
                    'last_sync': last_sync.isoformat() if last_sync else None,
                }

            return Response(summary)

        except Exception as e:
            logger.exception("Failed to build usage summary: %s", e)
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # ── sync ─────────────────────────────────────────────────────

    @action(detail=True, methods=['post'], url_path='sync')
    def sync(self, request, pk=None):
        """
        Trigger a sync for the integration.

        Refreshes the connection and updates metadata.
        """
        integration = self.get_object()
        try:
            from .scm_providers import get_provider, SCMProviderError

            provider = get_provider(
                provider_name=integration.provider_type,
                project_id='',
                access_token=integration.get_access_token(),
                base_url=integration.base_url,
                organization=integration.provider_organization(),
            )

            provider.verify_connection()
            integration.mark_verified(success=True)

            return Response({
                'success': True,
                'message': 'Sync completed successfully',
                'synced_at': (
                    integration.last_verified_at.isoformat()
                    if integration.last_verified_at else None
                ),
            })

        except SCMProviderError as e:
            integration.mark_verified(success=False, error=str(e))
            return Response(
                {'success': False, 'message': str(e)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except Exception as e:
            logger.exception("Sync failed: %s", e)
            return Response(
                {'success': False, 'message': f'Sync failed: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


class PipelineListView(APIView):
    """List CI/CD pipelines for the caller's org, provider-agnostic.

    Filters:
      - ``service_id``: scope to a specific ProjectService (via its
        CICDBinding.pipeline_id → Pipeline.external_project_id match).
      - ``status``: pipeline status (success/failed/running/...).
      - ``cicd_provider``: gitlab/github/jenkins/bitbucket/azure_devops.
      - ``environment``: development/staging/production.
    """
    permission_classes = [IsAuthenticated, Requires(GET='batch.read')]

    def get(self, request):
        from Projects.models import CICDBinding
        from .serializer import PipelineListSerializer

        qs = Pipeline.objects.filter(organisation=request.user.organisation)

        service_id = request.query_params.get('service_id')
        if service_id:
            binding_pipeline_ids = CICDBinding.objects.filter(
                project_service_id=service_id,
                project_service__project__organisation=request.user.organisation,
            ).values_list('pipeline_id', flat=True)
            qs = qs.filter(external_project_id__in=list(binding_pipeline_ids))

        for field in ('status', 'cicd_provider', 'environment'):
            val = request.query_params.get(field)
            if val:
                qs = qs.filter(**{field: val})

        qs = qs.select_related('project').prefetch_related('jobs').order_by('-id')

        try:
            limit = min(int(request.query_params.get('limit', 50)), 200)
        except ValueError:
            limit = 50
        qs = qs[:limit]

        return Response({'results': PipelineListSerializer(qs, many=True).data})


class DeploymentListView(APIView):
    """List runtime CI/CD deployment events for the caller's org.

    A ``providers.Deployment`` row is created each time a Pipeline
    reaches a terminal status against a specific environment. Distinct
    from the static ``Projects.ProjectDeployment`` config rows.

    Filters:
      - ``service_id``: scope via CodeChange → GitlabProject → ProjectService.
      - ``environment``, ``status``: exact match.
    """
    permission_classes = [IsAuthenticated, Requires(GET='batch.read')]

    def get(self, request):
        from .serializer import DeploymentListSerializer

        org = request.user.organisation
        qs = Deployment.objects.filter(code_change__organisation=org)

        service_id = request.query_params.get('service_id')
        if service_id:
            qs = qs.filter(code_change__gitlab_project__project_services__id=service_id)

        for field in ('environment', 'status'):
            val = request.query_params.get(field)
            if val:
                qs = qs.filter(**{field: val})

        qs = qs.select_related('code_change', 'pipeline').order_by('-deployed_at')

        try:
            limit = min(int(request.query_params.get('limit', 50)), 200)
        except ValueError:
            limit = 50
        qs = qs[:limit]

        return Response({'results': DeploymentListSerializer(qs, many=True).data})


