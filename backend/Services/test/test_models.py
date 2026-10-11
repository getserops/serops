"""
Unit Tests for Services Models

Tests cover:
- Service base model
- SCMService (GitLab, GitHub integration)
- InfraService (Database, Cache, etc.)
- CustomService
- Model inheritance
- Unique constraints
- Category auto-assignment
"""

from django.test import TestCase
from django.db import IntegrityError
from django.utils import timezone
from Services.models import Service, SCMService, InfraService, CustomService
from Projects.models import Project
from Organisations.models import Organisations


class TestServiceModel(TestCase):
    """Test cases for base Service model."""

    def setUp(self):
        """Set up test organization and project."""
        self.org = Organisations.objects.create(
            name="Test Org"
        )
        self.project = Project.objects.create(
            name="Test Project",
            description="Test Description",
            organisation=self.org
        )

    def test_service_creation(self):
        """Test basic service creation."""
        service = Service.objects.create(
            project=self.project,
            name="Test Service",
            description="A test service",
            category="custom",
            status="active"
        )
        
        self.assertEqual(service.name, "Test Service")
        self.assertEqual(service.category, "custom")
        self.assertEqual(service.status, "active")
        self.assertIsNotNone(service.created_at)
        self.assertIsNotNone(service.updated_at)

    def test_service_unique_name_per_project(self):
        """Test that service names must be unique within a project."""
        Service.objects.create(
            project=self.project,
            name="Duplicate Name",
            category="custom"
        )
        
        # Should raise IntegrityError for duplicate name in same project
        with self.assertRaises(IntegrityError):
            Service.objects.create(
                project=self.project,
                name="Duplicate Name",
                category="custom"
            )

    def test_service_same_name_different_projects(self):
        """Test that same service name can exist in different projects."""
        project2 = Project.objects.create(
            name="Another Project",
            organisation=self.org
        )
        
        Service.objects.create(
            project=self.project,
            name="Common Service",
            category="custom"
        )
        
        # Should succeed - different project
        service2 = Service.objects.create(
            project=project2,
            name="Common Service",
            category="custom"
        )
        
        self.assertIsNotNone(service2.id)

    def test_service_status_choices(self):
        """Test all status choices work correctly."""
        statuses = ["active", "inactive", "error", "maintenance"]
        
        for index, status in enumerate(statuses):
            service = Service.objects.create(
                project=self.project,
                name=f"Service {index}",
                category="custom",
                status=status
            )
            self.assertEqual(service.status, status)

    def test_service_ordering(self):
        """Test services are ordered by name."""
        Service.objects.create(project=self.project, name="Zebra", category="custom")
        Service.objects.create(project=self.project, name="Apple", category="custom")
        Service.objects.create(project=self.project, name="Mango", category="custom")
        
        services = list(Service.objects.all())
        
        self.assertEqual(services[0].name, "Apple")
        self.assertEqual(services[1].name, "Mango")
        self.assertEqual(services[2].name, "Zebra")


class TestSCMService(TestCase):
    """Test cases for SCMService model."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organisation=self.org)

    def test_scm_service_creation(self):
        """Test SCM service creation."""
        scm = SCMService.objects.create(
            project=self.project,
            name="GitLab Repo",
            provider="gitlab",
            external_id="12345",
            external_url="https://gitlab.com/test/repo",
            access_token="test-token",
            default_branch="main"
        )
        
        self.assertEqual(scm.provider, "gitlab")
        self.assertEqual(scm.category, "scm")  # Auto-assigned
        self.assertEqual(scm.external_id, "12345")
        self.assertEqual(scm.default_branch, "main")

    def test_scm_category_auto_assignment(self):
        """Test that category is automatically set to 'scm'."""
        scm = SCMService.objects.create(
            project=self.project,
            name="GitHub Repo",
            provider="github",
            external_id="owner/repo",
            access_token="token"
        )
        
        # Category should be automatically set
        self.assertEqual(scm.category, "scm")

    def test_scm_unique_provider_external_id(self):
        """Test that provider+external_id combination is unique."""
        SCMService.objects.create(
            project=self.project,
            name="Repo 1",
            provider="gitlab",
            external_id="12345",
            access_token="token1"
        )
        
        # Should raise IntegrityError for duplicate provider+external_id
        with self.assertRaises(IntegrityError):
            SCMService.objects.create(
                project=self.project,
                name="Repo 2",
                provider="gitlab",
                external_id="12345",  # Same external_id
                access_token="token2"
            )

    def test_scm_webhook_fields(self):
        """Test webhook-related fields."""
        scm = SCMService.objects.create(
            project=self.project,
            name="Webhook Repo",
            provider="gitlab",
            external_id="99999",
            access_token="token",
            webhook_enabled=True,
            webhook_id="hook123",
            webhook_secret="secret456"
        )
        
        self.assertTrue(scm.webhook_enabled)
        self.assertEqual(scm.webhook_id, "hook123")
        self.assertEqual(scm.webhook_secret, "secret456")


class TestInfraService(TestCase):
    """Test cases for InfraService model."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organisation=self.org)

    def test_infra_service_creation(self):
        """Test infrastructure service creation."""
        infra = InfraService.objects.create(
            project=self.project,
            name="PostgreSQL DB",
            infra_type="database",
            provider="postgresql",
            host="localhost",
            port=5432,
            connection_string="postgresql://user:pass@localhost:5432/db"
        )
        
        self.assertEqual(infra.infra_type, "database")
        self.assertEqual(infra.provider, "postgresql")
        self.assertEqual(infra.category, "infrastructure")  # Auto-assigned
        self.assertEqual(infra.port, 5432)

    def test_infra_category_auto_assignment(self):
        """Test that category is automatically set to 'infrastructure'."""
        infra = InfraService.objects.create(
            project=self.project,
            name="Redis Cache",
            infra_type="cache",
            provider="redis"
        )
        
        self.assertEqual(infra.category, "infrastructure")

    def test_infra_health_check_fields(self):
        """Test health check related fields."""
        infra = InfraService.objects.create(
            project=self.project,
            name="API Service",
            infra_type="webserver",
            provider="nginx",
            health_check_url="http://localhost/health",
            health_status="healthy"
        )
        
        self.assertEqual(infra.health_check_url, "http://localhost/health")
        self.assertEqual(infra.health_status, "healthy")

    def test_infra_types(self):
        """Test various infrastructure types."""
        types = ["database", "cache", "queue", "storage", "container"]
        
        for idx, infra_type in enumerate(types):
            infra = InfraService.objects.create(
                project=self.project,
                name=f"Infra {idx}",
                infra_type=infra_type
            )
            self.assertEqual(infra.infra_type, infra_type)


class TestCustomService(TestCase):
    """Test cases for CustomService model."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organisation=self.org)

    def test_custom_service_creation(self):
        """Test custom service creation."""
        custom = CustomService.objects.create(
            project=self.project,
            name="External API",
            endpoint_url="https://api.example.com",
            api_key="secret-key-123"
        )
        
        self.assertEqual(custom.name, "External API")
        self.assertEqual(custom.category, "custom")  # Auto-assigned
        self.assertEqual(custom.endpoint_url, "https://api.example.com")
        self.assertEqual(custom.api_key, "secret-key-123")

    def test_custom_category_auto_assignment(self):
        """Test that category is automatically set to 'custom'."""
        custom = CustomService.objects.create(
            project=self.project,
            name="Microservice"
        )
        
        self.assertEqual(custom.category, "custom")

    def test_custom_optional_fields(self):
        """Test custom service with minimal fields."""
        custom = CustomService.objects.create(
            project=self.project,
            name="Simple Service"
            # endpoint_url and api_key are optional
        )
        
        self.assertEqual(custom.name, "Simple Service")
        self.assertFalse(custom.endpoint_url)
        self.assertEqual(custom.api_key, "")


class TestServiceInheritance(TestCase):
    """Test model inheritance behavior."""

    def setUp(self):
        """Set up test data."""
        self.org = Organisations.objects.create(name="Test Org")
        self.project = Project.objects.create(name="Test Project", organisation=self.org)

    def test_polymorphic_query(self):
        """Test querying all services returns all subtypes."""
        SCMService.objects.create(
            project=self.project,
            name="GitLab",
            provider="gitlab",
            external_id="1",
            access_token="token"
        )
        InfraService.objects.create(
            project=self.project,
            name="Database",
            infra_type="database"
        )
        CustomService.objects.create(
            project=self.project,
            name="API"
        )
        
        # Should return all services
        all_services = Service.objects.all()
        self.assertEqual(all_services.count(), 3)

    def test_specific_type_queries(self):
        """Test querying specific service types."""
        SCMService.objects.create(
            project=self.project,
            name="GitLab",
            provider="gitlab",
            external_id="1",
            access_token="token"
        )
        InfraService.objects.create(
            project=self.project,
            name="Database",
            infra_type="database"
        )
        
        scm_services = SCMService.objects.all()
        infra_services = InfraService.objects.all()
        
        self.assertEqual(scm_services.count(), 1)
        self.assertEqual(infra_services.count(), 1)
