"""Data migration — populate ProjectDeployment from existing state (Batch 48).

For every existing Project:
  * For every active ProjectEnvironment, create ONE ProjectDeployment
    with cluster=project.cluster, region='', namespace=''. That
    mirrors today's implicit ``(project × env × project.cluster)``
    batch tuple as an explicit row.
  * Projects with NO active envs get a single deployment with env=None
    so they don't lose their batch-creation path.

Idempotent: uses ``get_or_create`` so re-running (fresh install after
migration state confusion) is a no-op.

The reverse migration deletes all ProjectDeployment rows — safe
because the new ``Batch.deployment`` FK (added in Batch 49) is
``SET_NULL``, and the pre-Batch 48 batch pipeline still reads
``Batch.environment`` + ``Batch.cluster`` mirrors.
"""

from django.db import migrations


def seed_deployments(apps, schema_editor):
    Project = apps.get_model('Projects', 'Project')
    ProjectEnvironment = apps.get_model('Projects', 'ProjectEnvironment')
    ProjectDeployment = apps.get_model('Projects', 'ProjectDeployment')

    created_count = 0
    for project in Project.objects.all().iterator(chunk_size=200):
        active_envs = list(
            ProjectEnvironment.objects.filter(project=project, is_active=True)
        )
        if not active_envs:
            # Legacy zero-env project — create one deployment with
            # env=None so batch creation still routes correctly. The
            # new pipeline (Batch 49) handles env=None as "use project's
            # detected env at batch time" — matching the pre-Batch 48
            # fallback path in create_log_batch_with_project_name.
            ProjectDeployment.objects.get_or_create(
                project=project,
                environment=None,
                cluster=project.cluster,
                region='',
                namespace='',
                defaults={
                    'is_active': True,
                    'name': (project.cluster.name if project.cluster else 'default'),
                },
            )
            created_count += 1
            continue

        for env in active_envs:
            _, was_created = ProjectDeployment.objects.get_or_create(
                project=project,
                environment=env,
                cluster=project.cluster,
                region='',
                namespace='',
                defaults={
                    'is_active': True,
                    # Name mirrors the format ProjectDeployment.suggest_name
                    # would produce on save() — replicated here because
                    # migration ops run against historical model instances
                    # that don't carry custom methods.
                    'name': _suggest_name(project.cluster, env),
                },
            )
            if was_created:
                created_count += 1

    if created_count:
        print(f'[Batch 48 migration] Created {created_count} ProjectDeployment row(s).')


def _suggest_name(cluster, environment):
    parts = []
    if cluster is not None:
        parts.append(cluster.name)
    if environment is not None:
        parts.append(environment.name)
    return ' / '.join(parts) if parts else 'default'


def unseed_deployments(apps, schema_editor):
    """Reverse: drop all ProjectDeployment rows.

    Safe because the pre-Batch 48 pipeline reads Batch.environment +
    Batch.cluster mirrors, not the deployment FK.
    """
    ProjectDeployment = apps.get_model('Projects', 'ProjectDeployment')
    ProjectDeployment.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('Projects', '0013_projectdeployment'),
    ]

    operations = [
        migrations.RunPython(seed_deployments, reverse_code=unseed_deployments),
    ]
