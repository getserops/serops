"""Q5-5 (2026-09-21): per-org alert-ingest secret rotation.

    POST /api/organisation/alert-secret/rotate/    (admin only)
    GET  /api/organisation/alert-secret/            (admin only)

Rotate returns a fresh plaintext secret ONCE — SerOps stores only its
SHA-256 hash + a display prefix. Callers are expected to update their
Alertmanager / Grafana / Datadog webhook Authorization header
immediately.

Reveal (GET) returns metadata only — no plaintext. Once rotated, the
old secret stops working the instant the new hash is persisted.
"""
from __future__ import annotations
from Middlewares.rbac import Requires
import hashlib
import logging
import secrets

from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Organisations.models import Organisations

logger = logging.getLogger(__name__)

_PLAINTEXT_PREFIX = 'serops_alert_'  # so operators recognise these tokens
_PREFIX_CAP = 12                     # matches the field's max_length


def _hash(plaintext: str) -> str:
    return hashlib.sha256(plaintext.encode('utf-8')).hexdigest()


class AlertSecretView(APIView):
    """GET metadata about the org's current alert-ingest secret."""
    permission_classes = [IsAuthenticated, Requires(GET='alerting.manage')]

    def get(self, request):
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return Response({'error': 'No organisation'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({
            'has_secret': bool(org.alert_ingest_secret_hash),
            'prefix': org.alert_ingest_secret_prefix or '',
            'rotated_at': org.alert_ingest_secret_rotated_at.isoformat()
                if org.alert_ingest_secret_rotated_at else None,
            'webhook_url_template': (
                f'/api/webhooks/alerts/<alertmanager|grafana|datadog>/{org.id}/'
            ),
            'unmatched_alerts': _unmatched_alerts(org),
        })


def _unmatched_alerts(org, days=7, limit=5):
    """Alerts of the last ``days`` that matched no service and were not
    analysed (phase 3 review SC-02), so an admin can fix the alert labels or
    the service names instead of reading a log line."""
    from datetime import timedelta
    from Data.models import AlertEvent
    qs = AlertEvent.objects.filter(organisation=org, match_status=AlertEvent.MATCH_UNMATCHED,
                                   received_at__gte=timezone.now() - timedelta(days=days))
    return {
        'count': qs.count(),
        'days': days,
        'latest': [
            {'alertname': e.alertname, 'source': e.source, 'service': e.service,
             'environment': e.environment, 'received_at': e.received_at.isoformat(),
             'detail': e.match_detail}
            for e in qs.order_by('-received_at')[:limit]
        ],
    }


class AlertSecretRotateView(APIView):
    """POST — generate a new per-org alert-ingest secret. Plaintext
    returned ONCE in the response body; only its SHA-256 hash is
    persisted."""
    permission_classes = [IsAuthenticated, Requires(POST='alerting.manage')]

    def post(self, request):
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return Response({'error': 'No organisation'}, status=status.HTTP_400_BAD_REQUEST)

        plaintext = _PLAINTEXT_PREFIX + secrets.token_urlsafe(32)
        org.alert_ingest_secret_hash = _hash(plaintext)
        org.alert_ingest_secret_prefix = plaintext[:_PREFIX_CAP]
        org.alert_ingest_secret_rotated_at = timezone.now()
        org.save(update_fields=[
            'alert_ingest_secret_hash',
            'alert_ingest_secret_prefix',
            'alert_ingest_secret_rotated_at',
        ])
        logger.info('Alert-ingest secret rotated for org=%s by user=%s',
                    org.id, getattr(request.user, 'id', None))
        return Response({
            'plaintext': plaintext,
            'prefix': org.alert_ingest_secret_prefix,
            'rotated_at': org.alert_ingest_secret_rotated_at.isoformat(),
            'message': (
                'Copy this secret now — SerOps will never show it again. '
                'Use it as the Bearer token in your Alertmanager / Grafana / '
                'Datadog webhook Authorization header.'
            ),
        }, status=status.HTTP_200_OK)
