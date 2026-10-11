from django.db import migrations


def migrate_gitlab_to_scm(apps, schema_editor):
    """
    Copy data from GitlabProject and ProjectService to new SCMService model.
    """
    GitlabProject = apps.get_model("providers", "GitlabProject")
    ProjectService = apps.get_model("Projects", "ProjectService")
    SCMService = apps.get_model("Services", "SCMService")
    
    migrated_count = 0
    
    for project_service in ProjectService.objects.filter(service_type="gitlab"):
        gitlab_project = project_service.gitlab_project
        if not gitlab_project:
            continue
        
        # Check if already migrated
        if SCMService.objects.filter(
            provider="gitlab", 
            external_id=gitlab_project.project_id
        ).exists():
            continue
        
        # Create new SCMService
        scm_service = SCMService.objects.create(
            project=project_service.project,
            name=gitlab_project.name,
            description=project_service.description or "",
            category="scm",
            status=project_service.status.lower() if project_service.status else "active",
            config={},
            provider="gitlab",
            external_id=gitlab_project.project_id,
            external_url=gitlab_project.gitlab_url,
            default_branch="main",
            access_token=gitlab_project.access_token,
            username=gitlab_project.username,
            webhook_enabled=gitlab_project.webhook,
            es_index_name=gitlab_project.es_index_name or "",
        )
        migrated_count += 1
    
    print(f"Migrated {migrated_count} GitlabProject(s) to SCMService")


def reverse_migration(apps, schema_editor):
    """Remove migrated SCMService entries"""
    SCMService = apps.get_model("Services", "SCMService")
    SCMService.objects.filter(provider="gitlab").delete()


class Migration(migrations.Migration):
    dependencies = [
        ("Services", "0001_initial_service_models"),
        ("providers", "0004_code_change_model"),
        ("Projects", "0005_project_app_logs_index_name"),
    ]

    operations = [
        migrations.RunPython(migrate_gitlab_to_scm, reverse_migration),
    ]
