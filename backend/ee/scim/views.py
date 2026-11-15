"""SCIM 2.0 endpoints (Enterprise, feature ``scim``), under /api/ee/scim/v2/.

Authenticated by an organisation's SCIM bearer token only (never a user
session); every resource is scoped to that organisation. Without the
license every request gets 403 and nothing changes. Every write is in the
audit log (``SCIM_*``, and ``TEAM_ROLE_CHANGE`` / ``TEAM_UPDATE`` with
``source: scim``) and rate limited per token.
"""
import logging
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header
from rest_framework.parsers import JSONParser
from rest_framework.renderers import JSONRenderer
from rest_framework.permissions import BasePermission
from rest_framework.response import Response
from rest_framework.throttling import SimpleRateThrottle
from rest_framework.views import APIView

from Data.audit import log_action
from Utils import edition

from . import protocol, service
from .protocol import ScimError

logger = logging.getLogger(__name__)

FEATURE = 'scim'


class ScimJSONParser(JSONParser):
    media_type = protocol.CONTENT_TYPE


class ScimJSONRenderer(JSONRenderer):
    """Okta and Entra ID send ``Accept: application/scim+json`` (RFC 7644 §3.1)."""
    media_type = protocol.CONTENT_TYPE
    format = 'scim'


class ScimTokenAuthentication(BaseAuthentication):
    """``Authorization: Bearer serops_scim_…``: sets ``request.scim_org``."""

    def authenticate(self, request):
        from ee.models import ScimToken
        header = get_authorization_header(request).split()
        if len(header) != 2 or header[0].lower() != b'bearer':
            raise exceptions.AuthenticationFailed('A SCIM bearer token is required')
        try:
            raw = header[1].decode()
        except UnicodeDecodeError:
            raise exceptions.AuthenticationFailed('Invalid token')
        token = (ScimToken.objects.select_related('organisation')
                 .filter(token_hash=service.hash_token(raw), revoked_at__isnull=True).first())
        if token is None:
            raise exceptions.AuthenticationFailed('Invalid or revoked token')
        now = timezone.now()
        if token.last_used_at is None or (now - token.last_used_at).total_seconds() > 60:
            ScimToken.objects.filter(pk=token.pk).update(last_used_at=now)
        request.scim_org = token.organisation
        request.scim_token = token
        # No user: SCIM acts for the organisation (audit entries have no user).
        from django.contrib.auth.models import AnonymousUser
        return AnonymousUser(), token

    def authenticate_header(self, request):
        return 'Bearer realm="SerOps SCIM"'


class ScimLicensed(BasePermission):
    message = 'SCIM provisioning needs a SerOps Enterprise license with "scim".'

    def has_permission(self, request, view):
        return getattr(request, 'scim_org', None) is not None and edition.has_feature(FEATURE)


class ScimTokenThrottle(SimpleRateThrottle):
    scope = 'scim'

    def get_cache_key(self, request, view):
        token = getattr(request, 'scim_token', None)
        return self.cache_format % {'scope': self.scope, 'ident': token.pk if token else self.get_ident(request)}


class ScimView(APIView):
    authentication_classes = [ScimTokenAuthentication]
    permission_classes = [ScimLicensed]
    throttle_classes = [ScimTokenThrottle]
    parser_classes = [ScimJSONParser, JSONParser]
    renderer_classes = [ScimJSONRenderer, JSONRenderer]

    def handle_exception(self, exc):
        if isinstance(exc, ScimError):
            return self.scim(exc.body(), exc.status)
        if isinstance(exc, exceptions.APIException):
            response = super().handle_exception(exc)
            detail = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
            body = ScimError(response.status_code, detail).body()
            return self.scim(body, response.status_code, headers=dict(response.items()))
        logger.exception('SCIM request failed')
        return self.scim(ScimError(500, 'Internal error').body(), 500)

    @staticmethod
    def scim(data, status=200, headers=None):
        response = Response(data, status=status, content_type=protocol.CONTENT_TYPE)
        for key, value in (headers or {}).items():
            if key.lower() in ('www-authenticate', 'retry-after'):
                response[key] = value
        return response

    @property
    def org(self):
        return self.request.scim_org

    def audit(self, action, details):
        log_action(self.request, action, {**details, 'source': 'scim', 'scim_token': self.request.scim_token.name},
                   organisation=self.org)


# --- Discovery ------------------------------------------------------------------

class ServiceProviderConfigView(ScimView):
    def get(self, request):
        return self.scim(protocol.service_provider_config())


class SchemasView(ScimView):
    def get(self, request, schema_id=None):
        items = protocol.schemas()
        if schema_id:
            match = [s for s in items if s['id'] == schema_id]
            if not match:
                raise ScimError(404, 'Unknown schema')
            return self.scim(match[0])
        return self.scim(protocol.list_response(items, len(items), 1))


class ResourceTypesView(ScimView):
    def get(self, request, type_id=None):
        items = protocol.resource_types()
        if type_id:
            match = [t for t in items if t['id'] == type_id]
            if not match:
                raise ScimError(404, 'Unknown resource type')
            return self.scim(match[0])
        return self.scim(protocol.list_response(items, len(items), 1))


# --- Users ------------------------------------------------------------------------

def _identity(org, scim_id):
    from ee.models import ScimIdentity
    try:
        uuid.UUID(str(scim_id))
    except ValueError:
        raise ScimError(404, 'User not found')
    identity = ScimIdentity.objects.select_related('user').filter(organisation=org, scim_id=scim_id).first()
    if identity is None:
        raise ScimError(404, 'User not found')
    return identity


class UsersView(ScimView):
    def get(self, request):
        from Users.models import User

        from ee.models import ScimIdentity
        start, count = protocol.pagination(request.query_params)
        parsed = protocol.parse_filter(request.query_params.get('filter'),
                                       {'username', 'externalid', 'id', 'emails.value', 'emails'})
        users = User.objects.filter(organisation=self.org, is_demo=False).select_related('scim_identity')
        if parsed:
            attribute, value = parsed
            if attribute == 'username':
                # An existing member matches by sign-in email too, so the
                # identity provider links accounts made before SCIM.
                linked = ScimIdentity.objects.filter(organisation=self.org, user_name__iexact=value)
                users = users.filter(pk__in=linked.values('user_id')) | users.filter(
                    email__iexact=value, scim_identity__isnull=True)
            elif attribute == 'externalid':
                users = users.filter(scim_identity__external_id=value)
            elif attribute == 'id':
                users = users.filter(scim_identity__scim_id=value) if _is_uuid(value) else users.none()
            else:
                users = users.filter(email__iexact=value)
        users = users.order_by('pk')
        total = users.count()
        page = list(users[start - 1:start - 1 + count])
        exclude_groups = protocol.excluded(request.query_params, 'groups')
        resources = [protocol.user_resource(u, service.identity_for(u), with_groups=not exclude_groups) for u in page]
        return self.scim(protocol.list_response(resources, total, start))

    def post(self, request):
        from Users.models import User

        from ee.models import ScimIdentity
        fields = protocol.user_fields(request.data)
        existing = User.objects.filter(email__iexact=fields['email']).first()
        if existing is not None and (existing.organisation_id != self.org.pk or existing.is_demo):
            raise ScimError(409, 'This email belongs to an account outside this organisation', 'uniqueness')
        if ScimIdentity.objects.filter(organisation=self.org, user_name__iexact=fields['user_name']).exists():
            raise ScimError(409, 'A user with this userName exists', 'uniqueness')
        with transaction.atomic():
            if existing is not None:
                if hasattr(existing, 'scim_identity'):
                    raise ScimError(409, 'A user with this email exists', 'uniqueness')
                user = existing  # A member invited before SCIM: linked.
                created = False
            else:
                role, custom_role, active = service.initial_role(self.org.pk)
                user = User.objects.create(
                    email=fields['email'], username=fields['email'].split('@')[0][:20],
                    first_name=fields['first_name'], last_name=fields['last_name'],
                    organisation=self.org, role=role, custom_role=custom_role, is_active=active)
                user.set_unusable_password()
                user.save(update_fields=['password'])
                created = True
            identity = ScimIdentity.objects.create(
                user=user, organisation=self.org, scim_id=uuid.uuid4(), user_name=fields['user_name'],
                external_id=fields['external_id'], active=fields['active'])
            if not created:
                self._update_account(user, fields)
            self.audit('SCIM_USER_CREATE', {'affected_user': user.email, 'linked_existing': not created,
                                            'role': user.role, 'active': fields['active']})
            service.apply_access(request, user)
        user.refresh_from_db()
        return self.scim(protocol.user_resource(user, identity), 201)

    @staticmethod
    def _update_account(user, fields):
        from Users.models import User
        changed = []
        if fields['first_name'] != user.first_name:
            user.first_name, changed = fields['first_name'], changed + ['first_name']
        if fields['last_name'] != user.last_name:
            user.last_name, changed = fields['last_name'], changed + ['last_name']
        if fields['email'].lower() != user.email.lower():
            if User.objects.filter(email__iexact=fields['email']).exclude(pk=user.pk).exists():
                raise ScimError(409, 'Another account has this email', 'uniqueness')
            user.email, changed = fields['email'], changed + ['email']
        if changed:
            user.save(update_fields=changed)
        return changed


class UserDetailView(ScimView):
    def get(self, request, scim_id):
        identity = _identity(self.org, scim_id)
        return self.scim(protocol.user_resource(identity.user, identity,
                                                with_groups=not protocol.excluded(request.query_params, 'groups')))

    def put(self, request, scim_id):
        identity = _identity(self.org, scim_id)
        return self._save(identity, protocol.user_fields(request.data))

    def patch(self, request, scim_id):
        identity = _identity(self.org, scim_id)
        user = identity.user
        fields = {'user_name': identity.user_name, 'external_id': identity.external_id, 'email': user.email,
                  'first_name': user.first_name, 'last_name': user.last_name, 'active': identity.active}
        protocol.apply_user_patch(fields, (request.data or {}).get('Operations'))
        return self._save(identity, fields)

    def _save(self, identity, fields):
        from ee.models import ScimIdentity
        if fields['user_name'].lower() != identity.user_name.lower() and ScimIdentity.objects.filter(
                organisation=self.org, user_name__iexact=fields['user_name']).exclude(pk=identity.pk).exists():
            raise ScimError(409, 'A user with this userName exists', 'uniqueness')
        user = identity.user
        with transaction.atomic():
            changed = UsersView._update_account(user, fields)
            was_active = identity.active
            identity.user_name, identity.external_id, identity.active = \
                fields['user_name'], fields['external_id'], fields['active']
            identity.save()
            if was_active != identity.active:
                changed.append('active')
            if changed:
                self.audit('SCIM_USER_UPDATE', {'affected_user': user.email, 'changed': changed,
                                                'active': identity.active})
            service.apply_access(self.request, user)
        user.refresh_from_db()
        return self.scim(protocol.user_resource(user, identity))

    def delete(self, request, scim_id):
        """Deprovision: the account is deactivated, its tokens deleted, its
        SCIM groups and SSO teams left, and the SCIM link removed (the
        identity provider can create it again). The account itself is kept
        for the audit trail; an admin deletes it in Settings → Team."""
        identity = _identity(self.org, scim_id)
        user = identity.user
        with transaction.atomic():
            groups = list(user.scim_groups.filter(organisation=self.org))
            for group in groups:
                group.members.remove(user)
            identity.active = False
            identity.save(update_fields=['active'])
            service.apply_access(request, user)
            user.refresh_from_db()
            if user.is_active:
                # The last admin: deprovisioning would lock the organisation out.
                raise ScimError(409, "This is the organisation's last admin; make someone else admin first",
                                'mutability')
            identity.delete()
            self.audit('SCIM_USER_DELETE', {'affected_user': user.email, 'groups_left': [g.display_name for g in groups]})
        return Response(status=204)


def _is_uuid(value):
    try:
        uuid.UUID(str(value))
        return True
    except ValueError:
        return False


# --- Groups -------------------------------------------------------------------------

def _group(org, scim_id):
    from ee.models import ScimGroup
    if not _is_uuid(scim_id):
        raise ScimError(404, 'Group not found')
    group = ScimGroup.objects.filter(organisation=org, scim_id=scim_id).first()
    if group is None:
        raise ScimError(404, 'Group not found')
    return group


def _members(org, ids):
    """Accounts for SCIM user ids; an unknown id is an error (RFC 7644 3.5.2)."""
    from ee.models import ScimIdentity
    ids = [i for i in dict.fromkeys(ids)]
    bad = [i for i in ids if not _is_uuid(i)]
    found = list(ScimIdentity.objects.select_related('user').filter(organisation=org, scim_id__in=[
        i for i in ids if i not in bad]))
    if bad or len(found) != len(ids):
        raise ScimError(400, 'A member is not a user of this organisation', 'invalidValue')
    return [i.user for i in found]


class GroupsView(ScimView):
    def get(self, request):
        from ee.models import ScimGroup
        start, count = protocol.pagination(request.query_params)
        parsed = protocol.parse_filter(request.query_params.get('filter'), {'displayname', 'externalid', 'id'})
        groups = ScimGroup.objects.filter(organisation=self.org)
        if parsed:
            attribute, value = parsed
            if attribute == 'displayname':
                groups = groups.filter(display_name__iexact=value)
            elif attribute == 'externalid':
                groups = groups.filter(external_id=value)
            else:
                groups = groups.filter(scim_id=value) if _is_uuid(value) else groups.none()
        groups = groups.order_by('pk')
        total = groups.count()
        with_members = not protocol.excluded(request.query_params, 'members')
        resources = [protocol.group_resource(g, with_members=with_members) for g in groups[start - 1:start - 1 + count]]
        return self.scim(protocol.list_response(resources, total, start))

    def post(self, request):
        from ee.models import ScimGroup
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get('displayName') or '').strip()
        if not name:
            raise ScimError(400, 'displayName is required', 'invalidValue')
        if ScimGroup.objects.filter(organisation=self.org, display_name__iexact=name).exists():
            raise ScimError(409, 'A group with this displayName exists', 'uniqueness')
        members = _members(self.org, protocol._member_ids(data.get('members')))
        try:
            with transaction.atomic():
                group = ScimGroup.objects.create(organisation=self.org, scim_id=uuid.uuid4(), display_name=name[:255],
                                                 external_id=str(data.get('externalId') or '')[:255])
                self.audit('SCIM_GROUP_CREATE', {'group': group.display_name, 'external_id': group.external_id,
                                                 'members': len(members)})
                if members:
                    service.add_group_members(request, group, members)
        except IntegrityError:
            raise ScimError(409, 'A group with this displayName exists', 'uniqueness')
        return self.scim(protocol.group_resource(group), 201)


class GroupDetailView(ScimView):
    def get(self, request, scim_id):
        group = _group(self.org, scim_id)
        return self.scim(protocol.group_resource(group, with_members=not protocol.excluded(request.query_params, 'members')))

    def put(self, request, scim_id):
        group = _group(self.org, scim_id)
        data = request.data if isinstance(request.data, dict) else {}
        name = str(data.get('displayName') or '').strip()
        if not name:
            raise ScimError(400, 'displayName is required', 'invalidValue')
        members = _members(self.org, protocol._member_ids(data.get('members')))
        with transaction.atomic():
            renamed = self._rename(group, name, str(data.get('externalId') or group.external_id))
            changed = service.set_group_members(request, group, members)
            if renamed:
                service.reapply_all(request, group)
            self.audit('SCIM_GROUP_UPDATE', {'group': group.display_name, 'renamed': renamed,
                                             'members_changed': changed, 'members': len(members)})
        return self.scim(protocol.group_resource(group))

    def patch(self, request, scim_id):
        group = _group(self.org, scim_id)
        name, external_id, add, remove, replace = protocol.group_patch_plan((request.data or {}).get('Operations'))
        with transaction.atomic():
            renamed = self._rename(group, name if name is not None else group.display_name,
                                   external_id if external_id is not None else group.external_id)
            details = {'group': group.display_name}
            if replace is not None:
                details['members_set'] = service.set_group_members(request, group, _members(self.org, replace))
            if add:
                details['members_added'] = service.add_group_members(request, group, _members(self.org, add))
            if remove:
                # Removing someone who is not (or no longer) a member is not an error.
                details['members_removed'] = service.remove_group_members(
                    request, group, _known_members(self.org, remove))
            if renamed:
                details['renamed'] = True
                service.reapply_all(request, group)
            self.audit('SCIM_GROUP_UPDATE', details)
        # 204, as Entra ID and Okta expect (RFC 7644 3.5.2 allows it).
        return Response(status=204)

    @staticmethod
    def _rename(group, name, external_id):
        from ee.models import ScimGroup
        name, external_id = name.strip()[:255], (external_id or '')[:255]
        if name == group.display_name and external_id == group.external_id:
            return False
        if name.lower() != group.display_name.lower() and ScimGroup.objects.filter(
                organisation=group.organisation, display_name__iexact=name).exclude(pk=group.pk).exists():
            raise ScimError(409, 'A group with this displayName exists', 'uniqueness')
        group.display_name, group.external_id = name, external_id
        group.save(update_fields=['display_name', 'external_id', 'updated_at'])
        return True

    def delete(self, request, scim_id):
        group = _group(self.org, scim_id)
        with transaction.atomic():
            members = list(group.members.all())
            name = group.display_name
            group.members.clear()
            for user in members:
                service.apply_access(request, user)
            group.delete()
            self.audit('SCIM_GROUP_DELETE', {'group': name, 'members': len(members)})
        return Response(status=204)


def _known_members(org, ids):
    from ee.models import ScimIdentity
    return [i.user for i in ScimIdentity.objects.select_related('user').filter(
        organisation=org, scim_id__in=[i for i in ids if _is_uuid(i)])]
