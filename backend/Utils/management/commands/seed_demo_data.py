"""
Seed Demo Data Management Command

Creates a complete demo environment with realistic mock data.
Supports multiple scenarios for different client profiles.

Usage:
    python manage.py seed_demo_data --scenario=ecommerce
    python manage.py seed_demo_data --scenario=enterprise --clean
"""
import random
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone


class Command(BaseCommand):
    help = 'Seed the database with demo data for testing and demos'

    def add_arguments(self, parser):
        parser.add_argument(
            '--scenario',
            type=str,
            default='ecommerce',
            choices=['ecommerce', 'enterprise', 'startup', 'minimal'],
            help='Demo scenario to create (default: ecommerce)'
        )
        parser.add_argument(
            '--clean',
            action='store_true',
            help='Delete existing demo data before seeding'
        )
        parser.add_argument(
            '--org-name',
            type=str,
            default='Demo Organisation',
            help='Name for the demo organisation'
        )
        parser.add_argument(
            '--batches',
            type=int,
            default=20,
            help='Number of batches to create (default: 20)'
        )
        parser.add_argument(
            '--issues-per-batch',
            type=int,
            default=5,
            help='Average issues per batch (default: 5)'
        )

    def handle(self, *args, **options):
        scenario = options['scenario']
        clean = options['clean']
        org_name = options['org_name']
        batch_count = options['batches']
        issues_per_batch = options['issues_per_batch']

        self.stdout.write(self.style.NOTICE(f'🌱 Seeding demo data: scenario={scenario}'))

        if clean:
            self.clean_demo_data()

        try:
            with transaction.atomic():
                # Create organisation
                org = self.create_organisation(org_name)
                self.stdout.write(f'  ✓ Organisation: {org.name}')

                # Create users
                users = self.create_users(org, scenario)
                self.stdout.write(f'  ✓ Users: {len(users)} created')

                # Create provider integrations
                integrations = self.create_integrations(org, scenario)
                self.stdout.write(f'  ✓ Integrations: {len(integrations)} created')

                # Create projects with services
                projects = self.create_projects(org, scenario, integrations)
                self.stdout.write(f'  ✓ Projects: {len(projects)} created')

                # Create batches with AI analysis
                batches = self.create_batches(projects, batch_count)
                self.stdout.write(f'  ✓ Batches: {len(batches)} created')

                # Create issues
                issues = self.create_issues(batches, issues_per_batch)
                self.stdout.write(f'  ✓ Issues: {len(issues)} created')

                # Create pipelines and deployments
                pipelines = self.create_pipelines(projects, batches)
                self.stdout.write(f'  ✓ Pipelines: {len(pipelines)} created')

                # Create code changes
                code_changes = self.create_code_changes(projects, batches)
                self.stdout.write(f'  ✓ Code changes: {len(code_changes)} created')

            self.stdout.write(self.style.SUCCESS(f'\n✅ Demo data seeded successfully!'))
            self.stdout.write(f'\n📊 Summary:')
            self.stdout.write(f'   Organisation: {org.name} (ID: {org.id})')
            self.stdout.write(f'   Users: {len(users)}')
            self.stdout.write(f'   Projects: {len(projects)}')
            self.stdout.write(f'   Batches: {len(batches)}')
            self.stdout.write(f'   Issues: {len(issues)}')

        except Exception as e:
            raise CommandError(f'Failed to seed data: {e}')

    def clean_demo_data(self):
        """Remove existing demo data."""
        from Organisations.models import Organisations
        from Data.models import AIAnalyzedBatch, Issue
        
        self.stdout.write('  🗑️  Cleaning existing demo data...')
        
        # Delete demo organisations (cascades to related data)
        demo_orgs = Organisations.objects.filter(name__icontains='Demo')
        count = demo_orgs.count()
        demo_orgs.delete()
        
        self.stdout.write(f'  ✓ Deleted {count} demo organisations')

    def create_organisation(self, name):
        """Create or get the demo organisation."""
        from Organisations.models import Organisations
        
        org, created = Organisations.objects.get_or_create(
            name=name,
            defaults={'website': 'demo.serops.io'}
        )
        return org

    def create_users(self, org, scenario):
        """Create users based on scenario."""
        from Users.models import User
        
        users = []
        user_specs = self._get_user_specs(scenario)
        
        for spec in user_specs:
            user, created = User.objects.get_or_create(
                email=spec['email'],
                defaults={
                    'username': spec['username'],
                    'organisation': org,
                    'role': spec['role'],
                    'is_active': True,
                }
            )
            if created:
                user.set_password('DemoPass123!')
                user.save()
            users.append(user)
        
        return users


    def _get_user_specs(self, scenario):
        """Get user specifications based on scenario.
        
        Valid roles: 'viewer', 'user', 'admin'
        """
        base_users = [
            {'email': 'admin@demo.serops.io', 'username': 'demo_admin', 'role': 'admin'},
            {'email': 'user@demo.serops.io', 'username': 'demo_user', 'role': 'user'},
        ]
        
        if scenario in ['enterprise', 'ecommerce']:
            base_users.extend([
                {'email': 'lead@demo.serops.io', 'username': 'demo_lead', 'role': 'admin'},
                {'email': 'viewer@demo.serops.io', 'username': 'demo_viewer', 'role': 'viewer'},
            ])
        
        return base_users


    def create_integrations(self, org, scenario):
        """Create provider integrations based on scenario."""
        from providers.models import ProviderIntegration
        
        integrations = []
        integration_specs = self._get_integration_specs(scenario)
        
        for spec in integration_specs:
            integration, _ = ProviderIntegration.objects.get_or_create(
                organisation=org,
                provider_type=spec['provider_type'],
                name=spec['name'],
                defaults={
                    'base_url': spec.get('base_url', ''),
                    'is_active': True,
                    'verification_status': 'verified',
                }
            )
            integrations.append(integration)
        
        return integrations

    def _get_integration_specs(self, scenario):
        """Get integration specs based on scenario."""
        if scenario == 'ecommerce':
            return [
                {'provider_type': 'github', 'name': 'GitHub Cloud', 'base_url': 'https://api.github.com'},
                {'provider_type': 'jenkins', 'name': 'Jenkins CI', 'base_url': 'https://jenkins.demo.io'},
            ]
        elif scenario == 'enterprise':
            return [
                {'provider_type': 'gitlab', 'name': 'GitLab Self-Hosted', 'base_url': 'https://gitlab.enterprise.io'},
                {'provider_type': 'jenkins', 'name': 'Jenkins Enterprise', 'base_url': 'https://jenkins.enterprise.io'},
            ]
        else:
            return [
                {'provider_type': 'github', 'name': 'GitHub', 'base_url': 'https://api.github.com'},
            ]

    def create_projects(self, org, scenario, integrations):
        """Create projects with services based on scenario."""
        from Projects.models import Project, ProjectEnvironment
        
        projects = []
        project_specs = self._get_project_specs(scenario)
        
        for spec in project_specs:
            project, _ = Project.objects.get_or_create(
                name=spec['name'],
                organisation=org,
                defaults={
                    'description': spec['description'],
                    'es_index_name': spec.get('es_index', f"logs-{spec['name'].lower().replace(' ', '-')}"),
                }
            )
            
            # Create default environments
            for env_name in ['production', 'staging', 'development']:
                ProjectEnvironment.objects.get_or_create(
                    project=project,
                    name=env_name,
                    defaults={
                        'branch_patterns': self._get_branch_patterns(env_name),
                        'is_active': True,
                    }
                )
            
            projects.append(project)
        
        return projects

    def _get_project_specs(self, scenario):
        """Get project specifications based on scenario."""
        if scenario == 'ecommerce':
            return [
                {'name': 'E-Commerce Platform', 'description': 'Main e-commerce application'},
                {'name': 'Payment Gateway', 'description': 'Payment processing service'},
                {'name': 'Inventory Service', 'description': 'Stock management system'},
            ]
        elif scenario == 'enterprise':
            return [
                {'name': 'Core Banking API', 'description': 'Core banking services'},
                {'name': 'Customer Portal', 'description': 'Customer-facing web app'},
                {'name': 'Analytics Platform', 'description': 'Business intelligence'},
            ]
        elif scenario == 'startup':
            return [
                {'name': 'Main App', 'description': 'Primary application'},
            ]
        else:  # minimal
            return [
                {'name': 'Demo Project', 'description': 'Minimal demo project'},
            ]

    def _get_branch_patterns(self, env_name):
        """Get branch patterns for environment."""
        patterns = {
            'production': ['main', 'master'],
            'staging': ['release/*', 'staging'],
            'development': ['develop', 'dev/*'],
        }
        return patterns.get(env_name, ['*'])

    def create_batches(self, projects, count):
        """Create AI analyzed batches."""
        from Data.models import AIAnalyzedBatch
        
        batches = []
        environments = ['production', 'staging', 'development']
        
        for i in range(count):
            project = random.choice(projects)
            env = random.choice(environments)
            
            # Spread batches over last 7 days
            timestamp = timezone.now() - timedelta(
                days=random.randint(0, 6),
                hours=random.randint(0, 23),
                minutes=random.randint(0, 59)
            )
            
            # Create realistic mock logs for service health
            logs = []
            log_levels = ['INFO', 'WARN', 'ERROR', 'CRITICAL']
            services = ['api-gateway', 'backend', 'auth-service', 'database', 'payment-service']
            
            for _ in range(random.randint(20, 50)):
                service = random.choice(services)
                level = random.choices(log_levels, weights=[0.7, 0.15, 0.1, 0.05])[0]
                logs.append({
                    'timestamp': (timestamp - timedelta(minutes=random.randint(0, 60))).isoformat(),
                    'level': level,
                    'service_name': service,
                    'message': f'Mock log message for {service} operation',
                    'component': service
                })

            batch = AIAnalyzedBatch.objects.create(
                batch_id=AIAnalyzedBatch.generate_batch_id(),
                project=project,
                environment=env,
                timestamp=timestamp,
                analyzed_at=timestamp + timedelta(minutes=2), # Ensure analyzed_at is set for MTTR
                issue_count=0,  # Will update after issues created
                data={
                    'logs': logs, # Populate logs
                    'logs_count': len(logs),
                    'metrics_summary': f'CPU: {random.randint(20, 80)}%, Memory: {random.randint(1, 4)}GB',
                    'services': services,
                },
                analysis_text=f'Analysis for {project.name} in {env}',
                model_name=random.choice(['gemini-2.5-flash', 'deepseek-chat']),
            )
            batches.append(batch)
        
        return batches


    def create_issues(self, batches, avg_per_batch):
        """Create issues for batches."""
        from Data.models import Issue
        
        issues = []
        severities = ['CRITICAL', 'WARNING', 'INFO']
        severity_weights = [0.1, 0.3, 0.6]  # 10% critical, 30% warning, 60% info
        
        statuses = ['OPEN', 'RESOLVED', 'MUTED']
        status_weights = [0.6, 0.3, 0.1]
        
        issue_templates = [
            ('CONNECTION_TIMEOUT', 'Connection timeout to {component}', 'network'),
            ('MEMORY_HIGH', 'High memory usage detected: {value}%', 'performance'),
            ('NULL_POINTER', 'Exception in {component}: NullPointerException', 'application'),
            ('SERVICE_UNAVAILABLE', 'Response time exceeded threshold: {value}ms', 'performance'),
            ('DISK_FULL', 'Disk usage critical: {value}%', 'infrastructure'),
        ]
        
        components = ['api-gateway', 'payment-service', 'inventory-service', 'auth-service', 'database']
        
        for batch in batches:
            # Vary issue count per batch
            issue_count = max(0, int(random.gauss(avg_per_batch, 2)))
            
            for _ in range(issue_count):
                template = random.choice(issue_templates)
                component = random.choice(components)
                severity = random.choices(severities, weights=severity_weights)[0]
                status = random.choices(statuses, weights=status_weights)[0]
                
                description_text = template[1].format(component=component, value=random.randint(80, 99))
                
                # Generate structured root cause
                root_cause = {
                    'category': template[2].capitalize(),
                    'description': f'Root cause found in {component}: {template[1]}',
                    'probability': random.randint(80, 99)
                }

                issue = Issue.objects.create(
                    batch=batch,
                    project=batch.project,
                    environment=batch.environment,
                    severity=severity,
                    status=status,
                    issue_type=template[0],
                    scope='SERVICE',
                    component=component,
                    description=f'{description_text}\n\nDetailed description of the issue in {component}',
                    recommendation=f'Check {component} for {template[2]} issues',
                    root_cause=root_cause, # Add structured root cause
                    error_class=template[0],
                )
                issues.append(issue)
            
            # Update batch issue count
            batch.issue_count = issue_count
            batch.save(update_fields=['issue_count'])
        
        return issues


    def create_pipelines(self, projects, batches):
        """Create CI/CD pipelines linked to services."""
        from providers.models import Pipeline, Job, GitlabProject
        from Projects.models import ProjectService
        
        pipelines = []
        statuses = ['success', 'failed', 'running']
        status_weights = [0.7, 0.2, 0.1]
        
        # Ensure projects have linked GitlabProjects and ProjectServices
        for project in projects:
            # Create GitlabProject mock (independent of Project)
            gl_project, _ = GitlabProject.objects.get_or_create(
                project_id=str(random.randint(1000, 9999)), # Use unique project_id
                organisation=project.organisation,
                defaults={
                    'gitlab_url': f'https://gitlab.com/demo/{project.name.lower().replace(" ", "-")}',
                    'name': project.name,
                    'username': 'demo-user',
                    'access_token': 'glpat-dummy-token',
                }
            )
            
            # Create ProjectService linked to it
            ProjectService.objects.get_or_create(
                project=project,
                name=f"{project.name} Service",
                defaults={'gitlab_project': gl_project}
            )

        for batch in batches[:20]:  # Create pipelines for first 20 batches
            status = random.choices(statuses, weights=status_weights)[0]
            
            # Find the gitlab project for this batch's project via ProjectService
            try:
                service = ProjectService.objects.filter(project=batch.project, gitlab_project__isnull=False).first()
                if not service:
                    continue
                gl_project = service.gitlab_project
            except Exception:
                continue

            pipeline = Pipeline.objects.create(
                organisation=batch.project.organisation,
                project=gl_project, # Link to GitlabProject
                cicd_provider='gitlab',
                pipeline_id=f'{random.randint(10000, 99999)}',
                status=status,
                branch='main' if random.random() > 0.3 else 'develop',
                environment=batch.environment,
                external_project_id=str(gl_project.project_id), # Use GL ID
                created_at=batch.timestamp - timedelta(minutes=random.randint(10, 60))
            )
            
            # Create jobs for pipeline
            job_names = ['checkout', 'build', 'test', 'deploy']
            for job_name in job_names:
                Job.objects.create(
                    pipeline=pipeline,
                    job_id=f'{job_name}-{random.randint(100, 999)}',
                    name=job_name,
                    status='success' if status == 'success' else random.choice(['success', 'failed']),
                    logs=f'[INFO] Running {job_name}...\n[INFO] Completed.',
                )
            
            pipelines.append(pipeline)
        
        return pipelines


    def create_code_changes(self, projects, batches):
        """Create code changes (commits)."""
        from providers.models import CodeChange
        
        code_changes = []
        
        commit_messages = [
            'feat: Add user authentication',
            'fix: Resolve memory leak in worker',
            'chore: Update dependencies',
            'docs: Update API documentation',
            'refactor: Simplify database queries',
            'test: Add integration tests',
            'ci: Update deployment workflow',
            'perf: Optimize image loading',
        ]
        
        authors = [
            ('John Doe', 'john.doe@demo.io'),
            ('Jane Smith', 'jane.smith@demo.io'),
            ('Bob Wilson', 'bob.wilson@demo.io'),
        ]
        
        for batch in batches[:15]:  # Create code changes for first 15 batches
            author, email = random.choice(authors)
            
            code_change = CodeChange.objects.create(
                organisation=batch.project.organisation,
                provider='github',
                project_id=str(batch.project.id),
                commit_sha=f'{random.randint(0, 0xFFFFFFFF):08x}{random.randint(0, 0xFFFF):04x}',
                author_name=author,
                author_email=email,
                commit_message=random.choice(commit_messages),
                timestamp=batch.timestamp - timedelta(hours=random.randint(1, 24)),
                branch='main',
                files_changed=random.randint(1, 20),
                additions=random.randint(10, 200),
                deletions=random.randint(5, 100),
            )
            code_changes.append(code_change)
        
        return code_changes

