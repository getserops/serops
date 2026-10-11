"""IngestKey CRUD API — org admins manage their OTLP tokens.

Endpoints (under ``/api/traces/keys/``):

    GET    /                    — list keys for caller's org (no plaintext)
    POST   /                    — create + return plaintext ONCE
    DELETE /<id>/               — revoke (soft-delete: is_active=False)

Design notes:

* Plaintext is returned ONLY on POST — never on subsequent reads
  (same model as GitHub personal access tokens). Users must copy it
  immediately or regenerate.
* Delete is a soft-delete (``is_active=False``) rather than hard delete,
  so audit logs + last_used_at survive for post-incident forensics.
* Multi-tenancy: all endpoints scoped to caller's org via the queryset.
* Admin-role required for create / delete (matches other Settings surfaces).
"""

import logging

from rest_framework import serializers, status, viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from Middlewares.rbac import IsAdminRole
from .models import IngestKey

logger = logging.getLogger(__name__)


class IngestKeyReadSerializer(serializers.ModelSerializer):
    """Read shape — never exposes the hash or plaintext."""

    class Meta:
        model = IngestKey
        fields = [
            'id', 'name', 'key_prefix', 'is_active',
            'last_used_at', 'created_at',
        ]


class IngestKeyCreateSerializer(serializers.ModelSerializer):
    """Create shape — accepts just `name`; server generates the key."""

    class Meta:
        model = IngestKey
        fields = ['name']


class IngestKeyViewSet(viewsets.ViewSet):
    """CRUD (list, create, destroy) for the caller's org's IngestKeys."""

    permission_classes = [IsAuthenticated, IsAdminRole]

    def _queryset(self, request):
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return IngestKey.objects.none()
        return IngestKey.objects.filter(organisation=org).order_by('-created_at')

    def list(self, request):
        keys = self._queryset(request)
        return Response(IngestKeyReadSerializer(keys, many=True).data)

    def create(self, request):
        org = getattr(request.user, 'organisation', None)
        if org is None:
            return Response(
                {'error': 'User has no organisation'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = IngestKeyCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        plaintext = IngestKey.generate_key()
        instance = IngestKey(
            organisation=org,
            name=serializer.validated_data['name'],
            created_by=request.user,
        )
        instance.set_key(plaintext)
        instance.save()

        # Plaintext returned ONCE. This is the ONLY time the user will
        # see it — mirror GitHub PAT UX.
        data = IngestKeyReadSerializer(instance).data
        data['plaintext'] = plaintext
        data['message'] = (
            'Copy this key now — SerOps will never show it again. '
            'Store it in your OTEL Collector config as a Bearer token.'
        )
        logger.info(
            'IngestKey created: org=%s id=%s prefix=%s by user=%s',
            org.id, instance.pk, instance.key_prefix, request.user.pk,
        )
        return Response(data, status=status.HTTP_201_CREATED)

    def destroy(self, request, pk=None):
        instance = self._queryset(request).filter(pk=pk).first()
        if instance is None:
            return Response(
                {'error': 'IngestKey not found in your org'},
                status=status.HTTP_404_NOT_FOUND,
            )
        # Soft-delete — keep audit trail.
        instance.is_active = False
        instance.save(update_fields=['is_active'])
        logger.info(
            'IngestKey revoked: org=%s id=%s prefix=%s by user=%s',
            instance.organisation_id, instance.pk, instance.key_prefix, request.user.pk,
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
