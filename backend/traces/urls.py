"""URL routes for the traces app.

    POST   /api/traces/v1/traces               — OTLP HTTP JSON receiver
    GET    /api/traces/keys/                   — list IngestKeys (org-scoped)
    POST   /api/traces/keys/                   — create + return plaintext once
    DELETE /api/traces/keys/<id>/              — revoke (soft-delete)
    GET    /api/traces/traces/                 — list traces (paginated + filters)
    GET    /api/traces/traces/<trace_id>/      — trace detail with all spans
    GET    /api/traces/traces/services/        — distinct service names for filter UI
"""

from django.urls import path
from rest_framework.routers import DefaultRouter

from .ingest_key_views import IngestKeyViewSet
from .otlp_views import OTLPTracesReceiver
from .read_views import TraceReadViewSet

router = DefaultRouter()
router.register(r'keys', IngestKeyViewSet, basename='ingest-key')
router.register(r'traces', TraceReadViewSet, basename='trace')

urlpatterns = [
    path('v1/traces', OTLPTracesReceiver.as_view(), name='otlp-traces-receiver'),
    *router.urls,
]
