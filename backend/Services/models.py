from django.db import models


class Service(models.Model):
    """
    Base service model - uses Django model inheritance (multi-table inheritance).
    All specific service types inherit from this.
    """
    SERVICE_CATEGORIES = [
        ("scm", "Source Control"),
        ("infrastructure", "Infrastructure"),
        ("custom", "Custom"),
    ]
    
    STATUS_CHOICES = [
        ("active", "Active"),
        ("inactive", "Inactive"),
        ("error", "Error"),
        ("maintenance", "Maintenance"),
    ]
    
    project = models.ForeignKey(
        "Projects.Project",
        on_delete=models.CASCADE,
        related_name="new_services"
    )
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=20, choices=SERVICE_CATEGORIES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    config = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ["name"]
        unique_together = [("project", "name")]
    
    def __str__(self):
        return f"{self.name} ({self.get_category_display()})"


class SCMService(Service):
    """Source Control Management service (GitLab, GitHub, etc.)"""
    PROVIDER_CHOICES = [
        ("gitlab", "GitLab"),
        ("github", "GitHub"),
        ("bitbucket", "Bitbucket"),
        ("azure_devops", "Azure DevOps"),
    ]
    
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    external_id = models.CharField(max_length=255, db_index=True)
    external_url = models.URLField(blank=True, max_length=500)
    default_branch = models.CharField(max_length=100, default="main")
    
    access_token = models.CharField(max_length=512)
    username = models.CharField(max_length=255, blank=True)
    
    webhook_enabled = models.BooleanField(default=False)
    webhook_id = models.CharField(max_length=100, blank=True, null=True)
    webhook_secret = models.CharField(max_length=255, blank=True, null=True)
    
    es_index_name = models.CharField(max_length=255, blank=True, null=True)
    
    class Meta:
        verbose_name = "SCM Service"
        verbose_name_plural = "SCM Services"
        unique_together = [("provider", "external_id")]
    
    def save(self, *args, **kwargs):
        self.category = "scm"
        super().save(*args, **kwargs)


class InfraService(Service):
    """Infrastructure service (Database, Cache, etc.)"""
    INFRA_TYPES = [
        ("database", "Database"),
        ("cache", "Cache"),
        ("queue", "Message Queue"),
        ("storage", "Object Storage"),
        ("container", "Container Registry"),
        ("kubernetes", "Kubernetes"),
        ("cdn", "CDN"),
        ("webserver", "Web Server"),
    ]
    
    PROVIDERS = [
        ("postgresql", "PostgreSQL"),
        ("mysql", "MySQL"),
        ("mongodb", "MongoDB"),
        ("redis", "Redis"),
        ("elasticsearch", "Elasticsearch"),
        ("rabbitmq", "RabbitMQ"),
        ("kafka", "Kafka"),
        ("s3", "AWS S3"),
        ("docker", "Docker"),
        ("k8s", "Kubernetes"),
        ("nginx", "Nginx"),
        ("apache", "Apache"),
    ]
    
    infra_type = models.CharField(max_length=20, choices=INFRA_TYPES)
    provider = models.CharField(max_length=20, choices=PROVIDERS, blank=True)
    
    host = models.CharField(max_length=255, blank=True)
    port = models.IntegerField(null=True, blank=True)
    connection_string = models.TextField(blank=True)
    
    health_check_url = models.URLField(blank=True, null=True, max_length=500)
    last_health_check = models.DateTimeField(null=True, blank=True)
    health_status = models.CharField(max_length=20, default="unknown")
    
    class Meta:
        verbose_name = "Infrastructure Service"
        verbose_name_plural = "Infrastructure Services"
    
    def save(self, *args, **kwargs):
        self.category = "infrastructure"
        super().save(*args, **kwargs)


class CustomService(Service):
    """Custom service for external APIs, microservices, etc."""
    endpoint_url = models.URLField(blank=True, null=True, max_length=500)
    api_key = models.CharField(max_length=512, blank=True)
    
    class Meta:
        verbose_name = "Custom Service"
        verbose_name_plural = "Custom Services"
    
    def save(self, *args, **kwargs):
        self.category = "custom"
        super().save(*args, **kwargs)
