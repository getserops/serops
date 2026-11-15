"""SCIM 2.0 provisioning (Enterprise, feature ``scim``): what a change means for an account.

The identity provider pushes users and groups. After every change that can
affect a person, ``apply_access`` brings their SerOps account in line, in
the same request:

- **Active**: the identity provider's ``active``, and, when the
  organisation refuses people outside mapped groups (default role
  "Refuse sign-in"), membership of a mapped group. An account that loses
  access is deactivated and every token it holds is deleted at once (its
  sessions and API tokens stop working on the next request).
- **Role**: from the SSO group rules, when "Update roles at every sign-in"
  is on (the identity provider decides), the same switch as for OIDC/SAML.
- **Teams**: the SSO team rules; only memberships SSO/SCIM added are removed.

Groups match the rules on their display name or their external ID (Entra
ID sends the group's object ID there), like groups in an SSO assertion.
The last active admin of an organisation is never deactivated or demoted.
"""
import logging
import secrets
import uuid

from django.db import transaction

from Data.audit import log_action

logger = logging.getLogger(__name__)

TOKEN_PREFIX = 'serops_scim_'


def hash_token(raw):
    import hashlib
    return hashlib.sha256(raw.encode()).hexdigest()


def create_token(organisation, name, created_by):
    """(ScimToken, raw token). The raw token is returned once, never stored."""
    from ee.models import ScimToken
    raw = TOKEN_PREFIX + secrets.token_urlsafe(32)
    token = ScimToken.objects.create(organisation=organisation, name=name[:100], token_hash=hash_token(raw),
                                     prefix=raw[:len(TOKEN_PREFIX) + 4], created_by=created_by)
    return token, raw


def security_settings(organisation_id):
    from Users.models import SecuritySettings
    return SecuritySettings.objects.filter(organisation_id=organisation_id).first()


def group_keys(user):
    """Names and external IDs of the SCIM groups ``user`` is in."""
    keys = []
    for name, external in user.scim_groups.values_list('display_name', 'external_id'):
        keys.append(name)
        if external:
            keys.append(external)
    return keys


def revoke_credentials(user):
    """Delete every token of ``user`` (sessions and API tokens). Returns how many."""
    from knox.models import AuthToken
    from rest_framework.authtoken.models import Token
    count = AuthToken.objects.filter(user=user).delete()[0]
    count += Token.objects.filter(user=user).delete()[0]
    return count


def _is_last_admin(user):
    from Users.models import User
    return user.role == 'admin' and user.is_active and not User.objects.filter(
        organisation_id=user.organisation_id, role='admin', is_active=True).exclude(pk=user.pk).exists()


def apply_access(request, user):
    """Make ``user``'s active state, role and teams follow the identity provider. Returns what changed."""
    from Middlewares.rbac import role_key
    from Users import sso_roles
    from Users.sso_views import _resolve_key

    identity = getattr(user, 'scim_identity', None)
    sec = security_settings(user.organisation_id)
    groups = group_keys(user)
    org = user.organisation
    changes = []

    role = None
    if sec is not None:
        role = sso_roles.resolve_role(groups, sec.sso_role_mappings, sec.sso_default_role)
    denied_by_rules = sec is not None and role is None
    allowed = (identity is None or identity.active) and not denied_by_rules

    if not allowed and user.is_active:
        if _is_last_admin(user):
            logger.warning('SCIM: kept user %s active, the last admin of org %s', user.pk, user.organisation_id)
        else:
            user.is_active = False
            user.save(update_fields=['is_active'])
            revoked = revoke_credentials(user)
            reason = 'inactive at the identity provider' if identity is not None and not identity.active \
                else 'in no mapped group'
            log_action(request, 'SCIM_USER_DEACTIVATE', {'affected_user': user.email, 'reason': reason,
                                                         'tokens_revoked': revoked, 'source': 'scim'},
                       organisation=org)
            changes.append('deactivated')
    elif allowed and not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])
        log_action(request, 'SCIM_USER_UPDATE', {'affected_user': user.email, 'change': 'reactivated',
                                                 'source': 'scim'}, organisation=org)
        changes.append('reactivated')

    if sec is not None and role is not None and sec.sso_sync_role and role_key(user) != role:
        new_role, custom_role = _resolve_key(sec, role)
        if new_role is not None:
            if user.role == 'admin' and new_role != 'admin' and _is_last_admin(user):
                logger.warning('SCIM: kept user %s admin, the last one of org %s', user.pk, user.organisation_id)
            else:
                old = role_key(user)
                user.role, user.custom_role = new_role, custom_role
                user.save(update_fields=['role', 'custom_role'])
                log_action(request, 'TEAM_ROLE_CHANGE', {'affected_user': user.email, 'role': role, 'old_role': old,
                                                         'source': 'scim', 'groups': groups[:50]}, organisation=org)
                changes.append('role')

    if sec is not None:
        added, removed = sso_roles.sync_teams(user, groups, sec.sso_team_mappings)
        if added or removed:
            log_action(request, 'TEAM_UPDATE', {'affected_user': user.email, 'added_to': added,
                                                'removed_from': removed, 'source': 'scim'}, organisation=org)
            changes.append('teams')
    return changes


def identity_for(user):
    """The SCIM identity of an existing account, created the first time the IdP sees it."""
    from ee.models import ScimIdentity
    identity = getattr(user, 'scim_identity', None)
    if identity is None:
        identity, _ = ScimIdentity.objects.get_or_create(
            user=user, defaults={'organisation_id': user.organisation_id, 'scim_id': uuid.uuid4(),
                                 'user_name': user.email, 'active': user.is_active})
    return identity


def initial_role(organisation_id):
    """(role, custom_role, active) for an account the identity provider creates.

    The default role of the SSO settings; with "Refuse sign-in" as default
    the account is created inactive and becomes active when it joins a
    mapped group (Entra ID and Okta create the user first, then add it to
    groups).
    """
    from Users.sso_roles import DENY
    from Users.sso_views import _resolve_key
    sec = security_settings(organisation_id)
    if sec is None:
        return 'viewer', None, True
    if sec.sso_default_role == DENY:
        return 'viewer', None, False
    role, custom = _resolve_key(sec, sec.sso_default_role)
    return (role or 'viewer'), custom, True


@transaction.atomic
def set_group_members(request, group, users):
    """Replace a group's members; apply access to everyone who joined or left."""
    before = set(group.members.values_list('pk', flat=True))
    after = {u.pk for u in users}
    group.members.set(users)
    return _reapply(request, group, before ^ after)


@transaction.atomic
def add_group_members(request, group, users):
    before = set(group.members.values_list('pk', flat=True))
    group.members.add(*users)
    return _reapply(request, group, {u.pk for u in users} - before)


@transaction.atomic
def remove_group_members(request, group, users):
    before = set(group.members.values_list('pk', flat=True))
    group.members.remove(*users)
    return _reapply(request, group, {u.pk for u in users} & before)


def reapply_all(request, group):
    """After a group's name or external ID changed, or before it is deleted."""
    return _reapply(request, group, set(group.members.values_list('pk', flat=True)))


def _reapply(request, group, user_ids):
    from Users.models import User
    for user in User.objects.filter(pk__in=user_ids, organisation_id=group.organisation_id).select_related(
            'scim_identity', 'organisation'):
        apply_access(request, user)
    return len(user_ids)
