"""
Unit Tests for Projects Models

Tests cover:
- Project model
- ProjectService model
- Project-Service relationships
- GitLab integration via ProjectService
- Unique constraints
"""

from django.test import TestCase
from django.db import IntegrityError
from Projects.models import Project, ProjectService
from Organisations.models import Organisations
from providers.models import GitlabProject


class TestProjectModel(TestCase):
    """Test cases for Project model."""

    def setUp(self):
        """Set up test organization."""
        self.org = Organisations.objects.create(
            name="Test Organization"
        )

    def test_project_creation(self):
        """Test basic project creation."""
        project = Project.objects.create(
            name="My Project",
            description="Project description",
            organisation=self.org
        )
        
        self.assertEqual(project.name, "My Project")
        self.assertEqual(project.description, "Project description")
        self.assertEqual(project.organisation, self.org)
        self.assertIsNotNone(project.created_at)
        self.assertIsNotNone(project.updated_at)

    def test_project_unique_name_per_org(self):
        """Test that project names must be unique within an organization."""
        Project.objects.create(
            name="Duplicate Project",
            organisation=self.org
        )
        
        # Should raise IntegrityError for duplicate name in same org
        with self.assertRaises(IntegrityError):
            Project.objects.create(
                name="Duplicate Project",
                organisation=self.org
            )

    def test_project_same_name_different_orgs(self):
        """Test that same project name can exist in different organizations."""
        org2 = Organisations.objects.create(
            name="Another Org"
        )
        
        Project.objects.create(
            name="Common Project",
            organisation=self.org
        )
        
        # Should succeed - different organization
        project2 = Project.objects.create(
            name="Common Project",
            organisation=org2
        )
        
        self.assertIsNotNone(project2.id)

    def test_project_optional_description(self):
        """Test project creation with optional description."""
        project = Project.objects.create(
            name="Minimal Project",
            organisation=self.org
            # description is optional
        )
        
        self.assertEqual(project.name, "Minimal Project")
        self.assertIsNone(project.description)

    def test_project_index_names(self):
        """Test Elasticsearch index name fields."""
        project = Project.objects.create(
            name="ES Project",
            organisation=self.org,
            es_index_name="project_logs_*",
            app_logs_index_name="app_logs_*"
        )
        
        self.assertEqual(project.es_index_name, "project_logs_*")
        self.assertEqual(project.app_logs_index_name, "app_logs_*")

    def test_project_cascade_delete(self):
        """Test that deleting an organization deletes its projects."""
        project = Project.objects.create(
            name="Test Project",
            organisation=self.org
        )
        
        org_id = self.org.id
        self.org.delete()
        
        # Project should be deleted
        self.assertEqual(Project.objects.filter(organisation_id=org_id).count(), 0)


class TestProjectServiceModel(TestCase):
    """Test cases for ProjectService model."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(
            name="Test Org"
        )
        self.project = Project.objects.create(
            name="Test Project",
            organisation=self.org
        )

    def test_custom_service_creation(self):
        """Test creating a custom project service."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Custom API",
            description="A custom API service",
            status="Active"
        )
        
        self.assertEqual(service.service_type, "custom")
        self.assertEqual(service.name, "Custom API")
        self.assertEqual(service.status, "Active")
        self.assertEqual(service.project, self.project)

    def test_gitlab_service_creation(self):
        """Test creating a GitLab project service."""
        gitlab_project = GitlabProject.objects.create(
            name="GitLab Repo",
            project_id="12345",
            access_token="test-token"
        )
        
        service = ProjectService.objects.create(
            project=self.project,
            service_type="gitlab",
            gitlab_project=gitlab_project,
            status="Active"
        )
        
        self.assertEqual(service.service_type, "gitlab")
        self.assertEqual(service.gitlab_project, gitlab_project)
        self.assertIsNotNone(service.id)

    def test_service_str_representation_custom(self):
        """Test string representation for custom service."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="My Service"
        )
        
        str_repr = str(service)
        self.assertIn("My Service", str_repr)
        self.assertIn(self.project.name, str_repr)

    def test_service_str_representation_gitlab(self):
        """Test string representation for GitLab service."""
        gitlab_project = GitlabProject.objects.create(
            name="GitLab Repo",
            project_id="12345",
            access_token="test-token"
        )
        
        service = ProjectService.objects.create(
            project=self.project,
            service_type="gitlab",
            gitlab_project=gitlab_project
        )
        
        str_repr = str(service)
        self.assertIn("GitLab Repo", str_repr)
        self.assertIn(self.project.name, str_repr)

    def test_service_str_representation_unnamed(self):
        """Test string representation for unnamed service."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="custom"
            # No name provided
        )
        
        str_repr = str(service)
        # An unnamed service is identified by its TYPE and project now
        # ("[Custom] - Test Project"), not the old placeholder literal
        # "Unnamed Service". The type-based label is more useful in an admin
        # list, where several unnamed services would otherwise be
        # indistinguishable from one another.
        self.assertIn("Custom", str_repr)
        self.assertIn(self.project.name, str_repr)
        self.assertNotIn("None", str_repr)

    def test_gitlab_project_set_null_on_delete(self):
        """Test that gitlab_project is set to null when GitlabProject is deleted."""
        gitlab_project = GitlabProject.objects.create(
            name="GitLab Repo",
            project_id="12345",
            access_token="test-token"
        )
        
        service = ProjectService.objects.create(
            project=self.project,
            service_type="gitlab",
            gitlab_project=gitlab_project
        )
        
        # Delete GitLab project
        gitlab_project.delete()
        
        # Service should still exist with gitlab_project=None
        service.refresh_from_db()
        self.assertIsNone(service.gitlab_project)

    def test_service_cascade_delete_with_project(self):
        """Test that services are deleted when project is deleted."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Test Service"
        )
        
        project_id = self.project.id
        self.project.delete()
        
        # Service should be deleted
        self.assertEqual(ProjectService.objects.filter(project_id=project_id).count(), 0)


class TestProjectServiceRelationships(TestCase):
    """Test relationships between Project and ProjectService."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(
            name="Test Org"
        )
        self.project = Project.objects.create(
            name="Test Project",
            organisation=self.org
        )

    def test_project_services_reverse_relation(self):
        """Test accessing services from project via reverse relation."""
        ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Service 1"
        )
        ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Service 2"
        )
        
        services = self.project.services.all()
        
        self.assertEqual(services.count(), 2)

    def test_multiple_projects_different_services(self):
        """Test that different projects can have separate services."""
        project2 = Project.objects.create(
            name="Project 2",
            organisation=self.org
        )
        
        ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Service A"
        )
        ProjectService.objects.create(
            project=project2,
            service_type="custom",
            name="Service B"
        )
        
        self.assertEqual(self.project.services.count(), 1)
        self.assertEqual(project2.services.count(), 1)


class TestUnifiedServiceModel(TestCase):
    """Test cases for the new unified service model (Phase 2 redesign).
    
    New SERVICE_TYPES: application, infrastructure, custom
    Legacy types (gitlab, github, etc.) still supported for backwards compatibility.
    """

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(name="Test Org")
        self.project = Project.objects.create(
            name="Test Project",
            organisation=self.org
        )

    def test_application_service_creation(self):
        """Test creating an application service (new unified type)."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="application",
            name="Payment API",
            description="Payment microservice"
        )
        
        self.assertEqual(service.service_type, "application")
        self.assertEqual(service.name, "Payment API")
        self.assertEqual(service.subtype, "")

    def test_infrastructure_service_with_subtype(self):
        """Test creating an infrastructure service with subtype."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="infrastructure",
            subtype="database",
            name="Main PostgreSQL"
        )
        
        self.assertEqual(service.service_type, "infrastructure")
        self.assertEqual(service.subtype, "database")

    def test_infrastructure_cache_subtype(self):
        """Test infrastructure service with cache subtype."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="infrastructure",
            subtype="cache",
            name="Redis Cache"
        )
        
        self.assertEqual(service.subtype, "cache")

    def test_infrastructure_queue_subtype(self):
        """Test infrastructure service with queue subtype."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="infrastructure",
            subtype="queue",
            name="RabbitMQ"
        )
        
        self.assertEqual(service.subtype, "queue")

    def test_custom_service_still_works(self):
        """Test that custom service type still works."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="custom",
            name="Legacy System"
        )
        
        self.assertEqual(service.service_type, "custom")

    def test_only_three_service_types_allowed(self):
        """Test that only application, infrastructure, custom types exist."""
        allowed_types = ['application', 'infrastructure', 'custom']
        actual_types = [t[0] for t in ProjectService.SERVICE_TYPES]
        self.assertEqual(actual_types, allowed_types)

    def test_default_service_type_is_application(self):
        """Test that default service_type is now 'application'."""
        service = ProjectService.objects.create(
            project=self.project,
            name="Default Test"
        )
        
        self.assertEqual(service.service_type, "application")

    def test_subtype_freeform_value(self):
        """Test that subtype accepts freeform values."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="infrastructure",
            subtype="kubernetes-cluster",
            name="K8s Prod"
        )
        
        self.assertEqual(service.subtype, "kubernetes-cluster")

    def test_application_with_subtype(self):
        """Test application service with subtype for categorization."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="application",
            subtype="backend",
            name="Order Service"
        )
        
        self.assertEqual(service.service_type, "application")
        self.assertEqual(service.subtype, "backend")

    def test_get_provider_display_name(self):
        """Test get_provider_display_name method returns correct value."""
        service = ProjectService.objects.create(
            project=self.project,
            service_type="application",
            name="Test Service"
        )
        
        display_name = service.get_provider_display_name()
        self.assertEqual(display_name, "Application")
