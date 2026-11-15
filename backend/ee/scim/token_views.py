"""SCIM tokens of an organisation (Settings → Provisioning (SCIM)).

    GET    /api/ee/scim/tokens/        the SCIM base URL and the tokens (never their value)
    POST   /api/ee/scim/tokens/        {"name": "..."} → the token, shown this once
    DELETE /api/ee/scim/tokens/<id>/   revoke

A token lets the identity provider create accounts, give roles and
deactivate people, so managing tokens takes every permission of an admin.
"""
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from Data.audit import log_action
from Middlewares.rbac import ROLE_PERMISSIONS, Requires, can_grant
from Utils import edition

from . import protocol, service

FEATURE = 'scim'


def _row(token):
    return {
        'id': token.pk, 'name': token.name, 'prefix': token.prefix,
        'created_at': token.created_at.isoformat(),
        'created_by': token.created_by.email if token.created_by else None,
        'last_used_at': token.last_used_at.isoformat() if token.last_used_at else None,
        'revoked_at': token.revoked_at.isoformat() if token.revoked_at else None,
    }


def _admin_only(request):
    if not can_grant(request.user, ROLE_PERMISSIONS['admin']):
        return Response({'error': 'Managing SCIM tokens needs every permission of an admin.'},
                        status=status.HTTP_403_FORBIDDEN)
    return None


class ScimTokensView(APIView):
    permission_classes = [IsAuthenticated, Requires(GET='settings.read', POST='settings.manage')]

    def get(self, request):
        from ee.models import ScimToken
        org = request.user.organisation
        tokens = ScimToken.objects.filter(organisation=org).select_related('created_by').order_by('-created_at')
        return Response({
            'licensed': edition.has_feature(FEATURE),
            'base_url': protocol.base_url(),
            'tokens': [_row(t) for t in tokens],
        })

    def post(self, request):
        if not edition.has_feature(FEATURE):
            return Response(edition.license_error(FEATURE), status=status.HTTP_403_FORBIDDEN)
        refused = _admin_only(request)
        if refused:
            return refused
        name = str(request.data.get('name') or '').strip()
        if not name or len(name) > 100:
            return Response({'error': 'Give the token a name (at most 100 characters).'}, status=400)
        token, raw = service.create_token(request.user.organisation, name, request.user)
        log_action(request, 'SCIM_TOKEN_CREATE', {'token': token.name, 'prefix': token.prefix})
        return Response({**_row(token), 'token': raw}, status=201)


class ScimTokenDetailView(APIView):
    permission_classes = [IsAuthenticated, Requires(DELETE='settings.manage')]

    def delete(self, request, pk):
        from ee.models import ScimToken
        refused = _admin_only(request)
        if refused:
            return refused
        token = ScimToken.objects.filter(organisation=request.user.organisation, pk=pk).first()
        if token is None:
            return Response({'error': 'Token not found'}, status=404)
        # Revoking works without the license, so a key can always be cut off.
        if token.revoked_at is None:
            token.revoked_at = timezone.now()
            token.save(update_fields=['revoked_at'])
            log_action(request, 'SCIM_TOKEN_REVOKE', {'token': token.name, 'prefix': token.prefix})
        return Response(status=204)
