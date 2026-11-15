"""SCIM 2.0 wire format (RFC 7643, RFC 7644): resources, filters, PATCH, errors.

Written for what Microsoft Entra ID and Okta send, which is a subset of the
RFC: ``eq`` filters on userName, externalId, displayName and id; PATCH with
a path (``active``, ``name.givenName``, ``emails[type eq "work"].value``,
``members``, ``members[value eq "…"]``) or without one (a dict of
attributes); Entra ID's capitalised ``Add``/``Replace``/``Remove`` and its
string booleans ("True"/"False"). Attributes SerOps does not keep (title,
manager, locale…) are accepted and ignored, as most service providers do,
so a provisioning cycle does not fail on them.
"""
import re

from django.conf import settings

USER_SCHEMA = 'urn:ietf:params:scim:schemas:core:2.0:User'
GROUP_SCHEMA = 'urn:ietf:params:scim:schemas:core:2.0:Group'
ENTERPRISE_USER = 'urn:ietf:params:scim:schemas:extension:enterprise:2.0:User'
LIST_SCHEMA = 'urn:ietf:params:scim:api:messages:2.0:ListResponse'
PATCH_SCHEMA = 'urn:ietf:params:scim:api:messages:2.0:PatchOp'
ERROR_SCHEMA = 'urn:ietf:params:scim:api:messages:2.0:Error'
CONTENT_TYPE = 'application/scim+json'
MAX_RESULTS = 200


class ScimError(Exception):
    def __init__(self, status, detail, scim_type=None):
        super().__init__(detail)
        self.status = status
        self.detail = detail
        self.scim_type = scim_type

    def body(self):
        body = {'schemas': [ERROR_SCHEMA], 'status': str(self.status), 'detail': self.detail}
        if self.scim_type:
            body['scimType'] = self.scim_type
        return body


def base_url():
    return f"{(settings.API_URL or '').rstrip('/')}/ee/scim/v2"


def _iso(dt):
    return dt.isoformat().replace('+00:00', 'Z') if dt else None


def as_bool(value):
    """SCIM booleans; Entra ID sends "True"/"False" strings in PATCH."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in ('true', 'false'):
        return value.strip().lower() == 'true'
    raise ScimError(400, f'Not a boolean: {value!r}', 'invalidValue')


# --- Resources ----------------------------------------------------------------

def user_resource(user, identity, *, with_groups=True):
    full = ' '.join(p for p in (user.first_name, user.last_name) if p)
    data = {
        'schemas': [USER_SCHEMA],
        'id': str(identity.scim_id),
        'userName': identity.user_name,
        'name': {'givenName': user.first_name or '', 'familyName': user.last_name or '', 'formatted': full},
        'displayName': full or user.email,
        'emails': [{'value': user.email, 'type': 'work', 'primary': True}],
        'active': identity.active,
        'meta': {
            'resourceType': 'User',
            'created': _iso(identity.created_at),
            'lastModified': _iso(identity.updated_at),
            'location': f'{base_url()}/Users/{identity.scim_id}',
        },
    }
    if identity.external_id:
        data['externalId'] = identity.external_id
    if with_groups:
        data['groups'] = [{'value': str(g.scim_id), 'display': g.display_name,
                           '$ref': f'{base_url()}/Groups/{g.scim_id}'} for g in user.scim_groups.all()]
    return data


def group_resource(group, *, with_members=True):
    data = {
        'schemas': [GROUP_SCHEMA],
        'id': str(group.scim_id),
        'displayName': group.display_name,
        'meta': {
            'resourceType': 'Group',
            'created': _iso(group.created_at),
            'lastModified': _iso(group.updated_at),
            'location': f'{base_url()}/Groups/{group.scim_id}',
        },
    }
    if group.external_id:
        data['externalId'] = group.external_id
    if with_members:
        from ee.models import ScimIdentity
        data['members'] = [
            {'value': str(i.scim_id), 'display': i.user_name, '$ref': f'{base_url()}/Users/{i.scim_id}'}
            for i in ScimIdentity.objects.filter(user__in=group.members.all()).order_by('user_name')]
    return data


def list_response(resources, total, start_index):
    return {'schemas': [LIST_SCHEMA], 'totalResults': total, 'itemsPerPage': len(resources),
            'startIndex': start_index, 'Resources': resources}


def pagination(params):
    """(start_index, count) from the query (1-based, RFC 7644 3.4.2.4)."""
    try:
        start = max(int(params.get('startIndex', 1)), 1)
        count = min(max(int(params.get('count', 100)), 0), MAX_RESULTS)
    except (TypeError, ValueError):
        raise ScimError(400, 'startIndex and count must be integers', 'invalidValue')
    return start, count


def excluded(params, attribute):
    names = {a.strip().lower() for a in str(params.get('excludedAttributes', '')).split(',')}
    return attribute.lower() in names


# --- Filters ----------------------------------------------------------------

_FILTER = re.compile(r'^\s*([A-Za-z][\w.:]*)\s+eq\s+"((?:[^"\\]|\\.)*)"\s*$', re.IGNORECASE)


def parse_filter(text, allowed):
    """(attribute, value) of an ``attr eq "value"`` filter; attribute lower-cased.

    Only equality on the attributes in ``allowed`` (what Entra ID and Okta
    use to find an existing resource); anything else is ``invalidFilter``.
    """
    if not text:
        return None
    match = _FILTER.match(text)
    if not match:
        raise ScimError(400, 'Only filters of the form: attribute eq "value" are supported', 'invalidFilter')
    attribute = match.group(1).lower()
    if attribute.startswith(USER_SCHEMA.lower() + ':'):
        attribute = attribute[len(USER_SCHEMA) + 1:]
    if attribute not in allowed:
        raise ScimError(400, f'Filtering on {match.group(1)} is not supported', 'invalidFilter')
    return attribute, match.group(2).replace('\\"', '"').replace('\\\\', '\\')


# --- Users: what we keep ------------------------------------------------------

def user_fields(data):
    """The fields SerOps keeps, from a full User resource (POST, PUT)."""
    if not isinstance(data, dict):
        raise ScimError(400, 'The body must be a JSON object', 'invalidSyntax')
    user_name = str(data.get('userName') or '').strip()
    if not user_name:
        raise ScimError(400, 'userName is required', 'invalidValue')
    name = data.get('name') if isinstance(data.get('name'), dict) else {}
    fields = {
        'user_name': user_name[:255],
        'external_id': str(data.get('externalId') or '')[:255],
        'email': _email_from(data.get('emails'), user_name),
        'first_name': str(name.get('givenName') or '')[:150],
        'last_name': str(name.get('familyName') or '')[:150],
        'active': as_bool(data['active']) if 'active' in data else True,
    }
    if not fields['first_name'] and not fields['last_name'] and data.get('displayName'):
        fields['first_name'], _, fields['last_name'] = str(data['displayName']).partition(' ')
    return fields


def _email_from(emails, user_name):
    """The primary (or work, or first) email; else the userName if it is an address."""
    if isinstance(emails, list):
        entries = [e for e in emails if isinstance(e, dict) and e.get('value')]
        for pick in (lambda e: e.get('primary') in (True, 'true', 'True'), lambda e: e.get('type') == 'work',
                     lambda e: True):
            for entry in entries:
                if pick(entry):
                    return str(entry['value']).strip()[:255]
    if '@' in user_name:
        return user_name.strip()[:255]
    raise ScimError(400, 'An email address is required (emails, or a userName that is one)', 'invalidValue')


_EMAIL_PATH = re.compile(r'^emails(\[type eq "(\w+)"\])?(\.value)?$', re.IGNORECASE)


def apply_user_patch(fields, operations):
    """Apply PATCH operations to the dict ``user_fields`` returns (in place)."""
    for op in _operations(operations):
        kind, path, value = op
        if path is None:
            if kind == 'remove' or not isinstance(value, dict):
                raise ScimError(400, 'A PATCH without a path needs an object value', 'noTarget')
            for key, item in value.items():
                _set_user_path(fields, kind, key, item)
        else:
            _set_user_path(fields, kind, path, value)


def _set_user_path(fields, kind, path, value):
    path_l = path.lower()
    if path_l.startswith(USER_SCHEMA.lower() + ':'):
        path_l = path_l[len(USER_SCHEMA) + 1:]
    removing = kind == 'remove'
    if path_l == 'active':
        if removing:
            raise ScimError(400, 'active cannot be removed', 'mutability')
        fields['active'] = as_bool(value)
    elif path_l == 'username':
        if removing or not str(value or '').strip():
            raise ScimError(400, 'userName is required', 'mutability')
        fields['user_name'] = str(value).strip()[:255]
    elif path_l == 'externalid':
        fields['external_id'] = '' if removing else str(value or '')[:255]
    elif path_l in ('name.givenname',):
        fields['first_name'] = '' if removing else str(value or '')[:150]
    elif path_l in ('name.familyname',):
        fields['last_name'] = '' if removing else str(value or '')[:150]
    elif path_l == 'name' and isinstance(value, dict):
        if 'givenName' in value:
            fields['first_name'] = str(value['givenName'] or '')[:150]
        if 'familyName' in value:
            fields['last_name'] = str(value['familyName'] or '')[:150]
    elif _EMAIL_PATH.match(path):
        if removing:
            return  # The email is the account's sign-in name: kept.
        if isinstance(value, list):
            fields['email'] = _email_from(value, fields['user_name'])
        elif str(value or '').strip():
            fields['email'] = str(value).strip()[:255]
    # Anything else (displayName, title, locale, the enterprise extension…)
    # is accepted and not kept.


# --- Groups ---------------------------------------------------------------------

_MEMBER_FILTER = re.compile(r'^members\[value eq "([^"]+)"\]$', re.IGNORECASE)


def group_patch_plan(operations):
    """What a Group PATCH asks for: (display_name or None, external_id or None,
    members to add, members to remove, replace members with this list or None)."""
    display_name = external_id = replace = None
    add, remove = [], []
    for kind, path, value in _operations(operations):
        path_l = (path or '').lower()
        if path is None:
            if not isinstance(value, dict):
                raise ScimError(400, 'A PATCH without a path needs an object value', 'noTarget')
            if 'displayName' in value:
                display_name = str(value['displayName'] or '')
            if 'externalId' in value:
                external_id = str(value['externalId'] or '')
            if 'members' in value:
                ids = _member_ids(value['members'])
                if kind == 'add':
                    add += ids
                else:
                    replace = ids
        elif path_l == 'displayname':
            display_name = str(value or '')
        elif path_l == 'externalid':
            external_id = '' if kind == 'remove' else str(value or '')
        elif path_l == 'members':
            if kind == 'add':
                add += _member_ids(value)
            elif kind == 'remove':
                if value is None:
                    replace = []
                else:
                    remove += _member_ids(value)
            else:
                replace = _member_ids(value)
        elif _MEMBER_FILTER.match(path or '') and kind == 'remove':
            remove.append(_MEMBER_FILTER.match(path).group(1))
        else:
            raise ScimError(400, f'Unsupported path for a Group: {path}', 'invalidPath')
    if display_name is not None and not display_name.strip():
        raise ScimError(400, 'displayName cannot be empty', 'invalidValue')
    return display_name, external_id, add, remove, replace


def _member_ids(value):
    if value is None:
        return []
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        raise ScimError(400, 'members must be a list of {"value": id}', 'invalidValue')
    return [str(m.get('value')) for m in value if isinstance(m, dict) and m.get('value')]


def _operations(operations):
    if not isinstance(operations, list) or not operations:
        raise ScimError(400, 'Operations must be a non-empty list', 'invalidSyntax')
    for op in operations:
        if not isinstance(op, dict):
            raise ScimError(400, 'Each operation must be an object', 'invalidSyntax')
        kind = str(op.get('op', '')).lower()
        if kind not in ('add', 'replace', 'remove'):
            raise ScimError(400, f'Unsupported op: {op.get("op")!r}', 'invalidSyntax')
        path = op.get('path')
        yield kind, (str(path) if path else None), op.get('value')


# --- Discovery --------------------------------------------------------------------

def service_provider_config():
    return {
        'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig'],
        'documentationUri': 'https://serops.ai/docs/enterprise/scim/',
        'patch': {'supported': True},
        'bulk': {'supported': False, 'maxOperations': 0, 'maxPayloadSize': 0},
        'filter': {'supported': True, 'maxResults': MAX_RESULTS},
        'changePassword': {'supported': False},
        'sort': {'supported': False},
        'etag': {'supported': False},
        'authenticationSchemes': [{
            'type': 'oauthbearertoken', 'name': 'Bearer token', 'primary': True,
            'description': 'A SCIM token created in SerOps, Settings → Provisioning (SCIM).',
        }],
        'meta': {'resourceType': 'ServiceProviderConfig', 'location': f'{base_url()}/ServiceProviderConfig'},
    }


def _attr(name, type_='string', **extra):
    return {'name': name, 'type': type_, 'multiValued': False, 'required': False, 'caseExact': False,
            'mutability': 'readWrite', 'returned': 'default', 'uniqueness': 'none', **extra}


def schemas():
    user = {
        'id': USER_SCHEMA, 'name': 'User', 'description': 'SerOps account',
        'attributes': [
            _attr('userName', required=True, uniqueness='server'),
            {**_attr('name', 'complex'), 'subAttributes': [_attr('givenName'), _attr('familyName'),
                                                           {**_attr('formatted'), 'mutability': 'readOnly'}]},
            {**_attr('displayName'), 'mutability': 'readOnly'},
            {**_attr('emails', 'complex'), 'multiValued': True,
             'subAttributes': [_attr('value'), _attr('type'), _attr('primary', 'boolean')]},
            _attr('active', 'boolean'),
            {**_attr('groups', 'complex'), 'multiValued': True, 'mutability': 'readOnly',
             'subAttributes': [_attr('value'), _attr('display')]},
        ],
        'meta': {'resourceType': 'Schema', 'location': f'{base_url()}/Schemas/{USER_SCHEMA}'},
    }
    group = {
        'id': GROUP_SCHEMA, 'name': 'Group', 'description': 'Identity provider group',
        'attributes': [
            _attr('displayName', required=True, uniqueness='server'),
            {**_attr('members', 'complex'), 'multiValued': True,
             'subAttributes': [_attr('value'), _attr('display')]},
        ],
        'meta': {'resourceType': 'Schema', 'location': f'{base_url()}/Schemas/{GROUP_SCHEMA}'},
    }
    return [user, group]


def resource_types():
    return [
        {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'], 'id': 'User', 'name': 'User',
         'endpoint': '/Users', 'schema': USER_SCHEMA,
         'meta': {'resourceType': 'ResourceType', 'location': f'{base_url()}/ResourceTypes/User'}},
        {'schemas': ['urn:ietf:params:scim:schemas:core:2.0:ResourceType'], 'id': 'Group', 'name': 'Group',
         'endpoint': '/Groups', 'schema': GROUP_SCHEMA,
         'meta': {'resourceType': 'ResourceType', 'location': f'{base_url()}/ResourceTypes/Group'}},
    ]
