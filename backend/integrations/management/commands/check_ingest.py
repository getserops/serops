"""Sample records from an integration and report tag/field presence.

The CLI counterpart of ``GET /api/integrations/observability/<id>/ingest-health/``
— same analyzer, same output shape. Useful for ops staff who want a
quick "am I tagging my logs correctly" check without opening the UI.

Usage:
    python manage.py check_ingest --integration 42
    python manage.py check_ingest --integration 42 --minutes 30 --limit 500
    python manage.py check_ingest --integration 42 --json > report.json
"""

import json

from django.core.management.base import BaseCommand, CommandError

from integrations.health import (
    MAX_SAMPLE_SIZE,
    MAX_SAMPLE_WINDOW_MIN,
    MIN_SAMPLE_SIZE,
    MIN_SAMPLE_WINDOW_MIN,
    collect_ingest_health,
)
from integrations.models import ObservabilityIntegration


class Command(BaseCommand):
    help = (
        'Sample recent records from an observability integration and report which '
        'canonical fields (service_name, project_name, environment, log_level, ...) '
        'are present, along with any auto-detected aliases (Datadog USM `service`, '
        'OpenTelemetry `service.name`, Kubernetes `app`, ...).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--integration', type=int, required=True,
            help='ObservabilityIntegration ID (find via GET /api/integrations/observability/)',
        )
        parser.add_argument(
            '--minutes', type=int, default=60,
            help=f'Sample window in minutes ({MIN_SAMPLE_WINDOW_MIN}-{MAX_SAMPLE_WINDOW_MIN}, default 60)',
        )
        parser.add_argument(
            '--limit', type=int, default=100,
            help=f'Max records to sample ({MIN_SAMPLE_SIZE}-{MAX_SAMPLE_SIZE}, default 100)',
        )
        parser.add_argument(
            '--json', action='store_true',
            help='Emit the full report as JSON instead of pretty text',
        )

    def handle(self, *args, **opts):
        try:
            integration = ObservabilityIntegration.objects.get(pk=opts['integration'])
        except ObservabilityIntegration.DoesNotExist:
            raise CommandError(
                f'ObservabilityIntegration {opts["integration"]} not found. '
                f'List with: GET /api/integrations/observability/'
            )

        report = collect_ingest_health(
            integration,
            sample_size=opts['limit'],
            sample_window_minutes=opts['minutes'],
        )

        if opts['json']:
            self.stdout.write(json.dumps(report.to_dict(), indent=2, default=str))
            return

        self._render_text(report)

    # ------------------------------------------------------------------
    # Text renderer
    # ------------------------------------------------------------------

    def _render_text(self, report) -> None:
        out = self.stdout
        w = self.style.WARNING
        s = self.style.SUCCESS
        e = self.style.ERROR

        out.write('=' * 60)
        out.write(f'SerOps Ingest Health — {report.integration_name} (ID: {report.integration_id})')
        out.write('=' * 60)
        out.write(f'Provider:       {report.provider} ({report.provider_type})')
        out.write(f'Sample:         {report.sample_size} records, last {report.sample_window_minutes} min')
        if report.sampled_at:
            out.write(f'Sampled at:     {report.sampled_at.strftime("%Y-%m-%d %H:%M:%S %Z")}')

        if report.error:
            out.write('')
            out.write(e(f'ERROR: {report.error}'))
            return

        out.write('')
        out.write('Canonical field presence:')
        out.write('')
        out.write('  ' + f'{"Canonical":<20} {"Present":<10} {"Aliases seen":<32} {"Missing":<10} {"Severity"}')
        out.write('  ' + '-' * 90)
        for f in report.fields:
            aliases = ', '.join(f'{a}:{c}' for a, c in sorted(f.alias_counts.items(), key=lambda x: -x[1])[:3])
            aliases = aliases or '—'
            missing = f'{f.missing_count}/{f.total}' if f.total else '—'
            present = f'{f.canonical_count}/{f.total} ({f.canonical_pct}%)' if f.total else '—'
            styled_sev = {
                'ok': s('✓ ok'),
                'info': ' ℹ info',
                'warning': w('⚠ warn'),
            }.get(f.severity, f.severity)
            out.write(f'  {f.canonical:<20} {present:<10} {aliases:<32} {missing:<10} {styled_sev}')

        if report.warnings:
            out.write('')
            out.write('Warnings:')
            for msg in report.warnings:
                out.write(f'  {w("⚠")} {msg}')

        if report.recommendations:
            out.write('')
            out.write('Recommendations:')
            for msg in report.recommendations:
                out.write(f'  ℹ {msg}')

        out.write('')
        out.write('Docs: https://serops.ai/docs/how-to/configure-data-collection/')
