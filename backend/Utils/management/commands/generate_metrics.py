"""
Generate Mock Metrics Management Command

Generates realistic time-series metrics for testing and development.

Usage:
    python manage.py generate_metrics --project=1 --hours=24
    python manage.py generate_metrics --project=1 --pattern=cpu_spike
"""
import sys
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

# Add qa-serops generators to path
QA_PATH = Path(__file__).parent.parent.parent.parent.parent / 'qa-serops'
sys.path.insert(0, str(QA_PATH))


class Command(BaseCommand):
    help = 'Generate mock metrics for testing'

    def add_arguments(self, parser):
        parser.add_argument(
            '--project',
            type=int,
            required=True,
            help='Project ID to generate metrics for'
        )
        parser.add_argument(
            '--hours',
            type=int,
            default=24,
            help='Hours of metrics data to generate (default: 24)'
        )
        parser.add_argument(
            '--interval',
            type=int,
            default=60,
            help='Interval between metrics in seconds (default: 60)'
        )
        parser.add_argument(
            '--service',
            type=str,
            default='api-gateway',
            help='Service name for metrics (default: api-gateway)'
        )
        parser.add_argument(
            '--pattern',
            type=str,
            choices=['normal', 'cpu_spike', 'memory_leak', 'dashboard'],
            default='normal',
            help='Metrics pattern to generate'
        )

    def handle(self, *args, **options):
        from Projects.models import Project

        project_id = options['project']
        hours = options['hours']
        interval = options['interval']
        service = options['service']
        pattern = options['pattern']

        # Validate project exists
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            raise CommandError(f'Project {project_id} not found')

        self.stdout.write(self.style.NOTICE(f'Generating metrics for: {project.name}'))
        self.stdout.write(f'   Pattern: {pattern}, Hours: {hours}, Interval: {interval}s')

        try:
            from generators.base import GeneratorConfig
            from generators.metrics import (
                MetricsGenerator, MetricPattern,
                CPUSpikeGenerator, MemoryLeakGenerator,
                DashboardMetricsGenerator
            )

            config = GeneratorConfig(
                org_id=project.organisation.id,
                project_id=project.id,
                environment='production',
                time_range_hours=hours,
            )

            count = (hours * 3600) // interval

            # Select pattern
            if pattern == 'cpu_spike':
                generator = CPUSpikeGenerator(config, service_name=service)
                metrics = {generator.metric_name: generator.generate_batch(count=count)}
            elif pattern == 'memory_leak':
                generator = MemoryLeakGenerator(config, service_name=service)
                metrics = {generator.metric_name: generator.generate_batch(count=count)}
            elif pattern == 'dashboard':
                generator = DashboardMetricsGenerator(config, service_name=service)
                metrics = generator.generate_batch(count=count)
            else:
                generator = MetricsGenerator(config, service_name=service)
                metrics = {generator.metric_name: generator.generate_batch(count=count)}

            total_points = sum(len(v) for v in metrics.values())
            self.stdout.write(f'   Generated {total_points} metric points across {len(metrics)} metrics')

            # Show summary
            self.stdout.write('\nMetrics summary:')
            for metric_name, points in metrics.items():
                if points:
                    values = [p.value for p in points]
                    self.stdout.write(
                        f'   {metric_name}: min={min(values):.1f}, max={max(values):.1f}, avg={sum(values)/len(values):.1f}'
                    )

            self.stdout.write(self.style.SUCCESS('\nMetrics generation complete!'))

        except ImportError as e:
            raise CommandError(f'Failed to import generators: {e}. Is qa-serops in path?')
