"""
Generate Mock Logs Management Command

Generates realistic log entries and optionally inserts them into Elasticsearch.

Usage:
    python manage.py generate_logs --project=1 --hours=24
    python manage.py generate_logs --project=1 --pattern=cascade_failure --insert
"""
import sys
from pathlib import Path
from datetime import datetime, timedelta
from django.core.management.base import BaseCommand, CommandError
from django.conf import settings

# Add qa-serops generators to path
QA_PATH = Path(__file__).parent.parent.parent.parent.parent / 'qa-serops'
sys.path.insert(0, str(QA_PATH))


class Command(BaseCommand):
    help = 'Generate mock log entries for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--project',
            type=int,
            required=True,
            help='Project ID to generate logs for'
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Hours of log data to generate (default: 24)'
        )
        parser.add_argument(
            '--count',
            type=int,
            default=500,
            help='Number of log entries to generate (default: 500)'
        )
        parser.add_argument(
            '--service',
            type=str,
            default='api-gateway',
            help='Service name for logs (default: api-gateway)'
        )
        parser.add_argument(
            '--error-ratio',
            type=float,
            default=0.1,
            help='Ratio of error logs (default: 0.1 = 10%%)'
        )
        parser.add_argument(
            '--pattern',
            type=str,
            choices=['normal', 'high_error', 'cascade_failure'],
            default='normal',
            help='Log pattern to generate'
        )
        parser.add_argument(
            '--insert',
            action='store_true',
            help='Insert logs into Elasticsearch'
        )
        parser.add_argument(
            '--batch-id',
            type=str,
            help='Associate logs with specific batch ID'
        )

    def handle(self, *args, **options):
        from Projects.models import Project
        
        project_id = options['project']
        hours = options['hours']
        count = options['count']
        service = options['service']
        error_ratio = options['error_ratio']
        pattern = options['pattern']
        insert = options['insert']
        batch_id = options.get('batch_id')

        # Validate project exists
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise CommandError(f'Project {project_id} not found')

        self.stdout.write(self.style.NOTICE(f'📝 Generating logs for: {project.name}'))
        self.stdout.write(f'   Pattern: {pattern}, Count: {count}, Hours: {hours}')

        try:
            from generators.base import GeneratorConfig
            from generators.logs import LogGenerator, LogPattern, CascadeFailureGenerator
            
            config = GeneratorConfig(
                org_id=project.organisation.id,
                project_id=project.id,
                environment='production',
                time_range_hours=hours,
            )

            # Select pattern
            if pattern == 'high_error':
                log_pattern = LogPattern(
                    name='high_error',
                    description='High error rate scenario',
                    error_ratio=0.5,
                    warning_ratio=0.3,
                )
                generator = LogGenerator(config, service_name=service, pattern=log_pattern)
                logs = generator.generate_batch(count=count)
            elif pattern == 'cascade_failure':
                generator = CascadeFailureGenerator(config, services=[
                    f'{service}-1', f'{service}-2', f'{service}-3'
                ])
                logs = generator.generate()
            else:
                generator = LogGenerator(config, service_name=service)
                logs = generator.generate_batch(count=count)

            self.stdout.write(f'   ✓ Generated {len(logs)} log entries')

            # Show sample
            self.stdout.write('\n📋 Sample logs:')
            for log in logs[:5]:
                level_style = {
                    'ERROR': self.style.ERROR,
                    'WARNING': self.style.WARNING,
                    'INFO': self.style.SUCCESS,
                }.get(log.level, self.style.NOTICE)
                self.stdout.write(f'   [{level_style(log.level)}] {log.message[:60]}...')

            # Insert if requested
            if insert:
                self._insert_to_elasticsearch(logs, project)
            else:
                self.stdout.write('\n💡 Use --insert to load into Elasticsearch')

            self.stdout.write(self.style.SUCCESS('\n✅ Log generation complete!'))

        except ImportError as e:
            raise CommandError(f'Failed to import generators: {e}. Is qa-serops in path?')

    def _insert_to_elasticsearch(self, logs, project):
        """Insert logs into Elasticsearch."""
        try:
            from elasticsearch import Elasticsearch, helpers
            
            es_host = getattr(settings, 'ELASTICSEARCH_HOST', 'http://localhost:9200')
            es = Elasticsearch([es_host])
            
            index_name = project.es_index_name or f'logs-{project.name.lower().replace(" ", "-")}'
            
            self.stdout.write(f'\n📤 Inserting into Elasticsearch index: {index_name}')
            
            # Prepare bulk actions
            actions = []
            for log in logs:
                actions.append({
                    '_index': index_name,
                    '_source': log.to_elasticsearch_doc(),
                })
            
            # Bulk insert
            success, failed = helpers.bulk(es, actions, raise_on_error=False)
            
            self.stdout.write(f'   ✓ Inserted: {success}, Failed: {len(failed) if failed else 0}')
            
        except ImportError:
            self.stdout.write(self.style.WARNING('⚠️  elasticsearch package not installed'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'❌ ES insert failed: {e}'))
