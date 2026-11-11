"""
Roles from the identity provider.

At each SSO sign-in the organisation's rules map the user's groups to a
role: the first rule whose group the user is in wins; with no match the
default role applies, or the sign-in is refused when the default is
``deny``. Grafana (role_attribute_path) and Airflow (AUTH_ROLES_MAPPING)
work the same way.
"""
import base64
import json
import logging

logger = logging.getLogger(__name__)

DENY = 'deny'


def builtin_roles():
    from Users.models import User
    return [r[0] for r in User.ROLE]


def valid_role_targets(organisation):
    """Role keys a rule or the default may name: built-in or custom."""
    from Users.models import CustomRole
    builtin = {r for r in builtin_roles() if r != 'custom'}
    return builtin | {r.key for r in CustomRole.objects.filter(organisation=organisation)}


def id_token_claims(token):
    """Claims of the ID token returned by the token endpoint.

    The token comes straight from the provider's token endpoint over the
    back channel, authenticated with the client secret, so OIDC Core
    3.1.3.7 lets us rely on TLS instead of checking its signature.
    """
    raw = token.get('id_token') if isinstance(token, dict) else None
    if not raw or raw.count('.') != 2:
        return {}
    try:
        payload = raw.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return claims if isinstance(claims, dict) else {}
    except (ValueError, TypeError):
        return {}


def extract_groups(claims, path):
    """The values at a dotted claim path, as a list of strings."""
    value = claims
    for part in (path or '').split('.'):
        if not part:
            return []
        if not isinstance(value, dict) or part not in value:
            return []
        value = value[part]
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, (str, int))]
    return []


def resolve_role(groups, mappings, default_role):
    """The role for these groups, or None when the sign-in is refused."""
    names = {g.strip().lower() for g in groups}
    # Some providers send group paths ("/sre"); match the last segment too.
    names |= {n.rsplit('/', 1)[-1] for n in names}
    for rule in mappings or []:
        group = str(rule.get('group', '')).strip().lower()
        if group and (group in names or group.rsplit('/', 1)[-1] in names):
            return rule.get('role')
    return None if default_role == DENY else default_role


def validate_mappings(organisation, mappings, default_role):
    """Errors in rules from the settings form (empty list when valid)."""
    errors = []
    targets = valid_role_targets(organisation)
    if not isinstance(mappings, list):
        return ['sso_role_mappings must be a list']
    if len(mappings) > 100:
        errors.append('At most 100 rules')
    for i, rule in enumerate(mappings, 1):
        if not isinstance(rule, dict):
            errors.append(f'Rule {i} must have a group and a role')
            continue
        if not str(rule.get('group', '')).strip():
            errors.append(f'Rule {i} has no group')
        if rule.get('role') not in targets:
            errors.append(f'Rule {i}: unknown role {rule.get("role")!r}')
    if default_role != DENY and default_role not in targets:
        errors.append(f'Unknown default role {default_role!r}')
    return errors


def normalise_domains(domains):
    """Lower-cased, de-duplicated domains; raises ValueError on a bad one."""
    if not isinstance(domains, list):
        raise ValueError('sso_domains must be a list')
    out = []
    for d in domains:
        d = str(d).strip().lower().lstrip('@')
        if not d:
            continue
        if '.' not in d or ' ' in d or '@' in d or len(d) > 253:
            raise ValueError(f'Not a domain: {d!r}')
        if d not in out:
            out.append(d)
    return out


def teams_for(groups, team_mappings):
    """Team ids whose mapped group the user is in."""
    names = {g.strip().lower() for g in groups}
    names |= {n.rsplit('/', 1)[-1] for n in names}
    wanted = set()
    for rule in team_mappings or []:
        group = str(rule.get('group', '')).strip().lower()
        if group and (group in names or group.rsplit('/', 1)[-1] in names):
            wanted.add(rule.get('team_id'))
    return wanted


def sync_teams(user, groups, team_mappings):
    """Put the user in the mapped teams of their groups, take them out of
    mapped teams of groups they left. Returns (added, removed) team names."""
    from Organisations.models import Team, TeamMembership
    managed = {r.get('team_id') for r in team_mappings or []}
    if not managed:
        return [], []
    teams = {t.pk: t for t in Team.objects.filter(pk__in=managed, organisation_id=user.organisation_id)}
    wanted = teams_for(groups, team_mappings) & set(teams)
    current = {m.team_id: m for m in TeamMembership.objects.filter(user=user, team_id__in=teams)}
    added = [teams[t].name for t in wanted - set(current)]
    TeamMembership.objects.bulk_create([TeamMembership(team_id=t, user=user, source='sso') for t in wanted - set(current)])
    gone = [m for t, m in current.items() if t not in wanted and m.source == 'sso']
    TeamMembership.objects.filter(pk__in=[m.pk for m in gone]).delete()
    return added, [teams[m.team_id].name for m in gone]


def validate_team_mappings(organisation, mappings):
    from Organisations.models import Team
    if not isinstance(mappings, list):
        return ['sso_team_mappings must be a list'], []
    errors, teams = [], []
    valid = {t.pk: t for t in Team.objects.filter(organisation=organisation)}
    for i, rule in enumerate(mappings, 1):
        if not isinstance(rule, dict) or not str(rule.get('group', '')).strip():
            errors.append(f'Team rule {i} has no group')
        elif rule.get('team_id') not in valid:
            errors.append(f'Team rule {i}: unknown team')
        else:
            teams.append(valid[rule['team_id']])
    return errors, teams
