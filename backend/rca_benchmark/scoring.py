"""
Fixed scoring rules for one scenario's issues. No model grades another
model: every check is a rule over the issues SerOps created.

An issue here is a dict with severity, confidence, component,
affected_services, description, root_cause, recommendation and
linked_commits, as the runner reads them from the Issue table.

Per incident:

  root_cause  the top issue names the right service and cause (and commit,
              when one is at fault): the headline number.
  strict   the TOP issue (worst severity, then highest confidence, then
           first created) names one of the right services in its component
           or affected services, its root cause and description match every
           cause group, it blames the right commit when one is at fault, and
           no distractor commit is blamed anywhere.
  lenient  the October 2026 rule: some issue mentions the service and the
           cause words anywhere in its text. Kept so older results compare.

Healthy windows pass when no issue is worse than ``benign_max``.
"""
import re

SEVERITY = {'UNKNOWN': 0, 'INFO': 1, 'WARNING': 2, 'CRITICAL': 3}
CONFIDENCE = {'UNKNOWN': 0, 'LOW': 1, 'MEDIUM': 2, 'HIGH': 3}


def _sev(issue):
    return SEVERITY.get(str(issue.get('severity') or '').upper(), 0)


def primary(issues):
    """The issue a reader sees first."""
    if not issues:
        return None
    ranked = sorted(enumerate(issues), key=lambda p: (
        -_sev(p[1]), -CONFIDENCE.get(str(p[1].get('confidence') or '').upper(), 0), p[0]))
    return ranked[0][1]


def _norm(name):
    name = str(name or '').strip().lower()
    return re.sub(r'\.(svc|prod|default)(\..*)?$', '', name)


def names_service(text, services):
    """One of ``services`` appears in ``text`` as a whole name (hyphens and
    dots are part of a name: 'redis' does not match 'redis-cache')."""
    text = str(text or '').lower()
    return any(re.search(rf'(?<![\w.-]){re.escape(_norm(s))}(?![\w-])', text) for s in services)


def _service_fields(issue):
    affected = issue.get('affected_services') or []
    return ' '.join([str(issue.get('component') or '')] + [_norm(a) for a in affected])


def matches_cause(text, groups):
    text = str(text or '').lower()
    return all(any(word.lower() in text for word in group) for group in groups)


def _commits(issue):
    return str(issue.get('linked_commits') or '').lower()


def blames(issue, sha):
    sha = sha[:7].lower()
    return sha in _commits(issue) or sha in str(issue.get('root_cause') or '').lower()


def score(answer, issues):
    """{'verdict', 'root_cause', 'lenient': bool, 'checks': {name: bool}, ...}."""
    alerting = [i for i in issues if _sev(i) >= SEVERITY['WARNING']]
    checks = {}

    if answer.get('benign_max'):
        worst = max((_sev(i) for i in issues), default=0)
        checks['silent'] = worst <= SEVERITY[answer['benign_max']]
        for sha in answer.get('wrong_shas') or []:
            checks[f'not blamed {sha[:7]}'] = not any(sha[:7] in _commits(i) for i in issues)
        ok = all(checks.values())
        return {'verdict': ok, 'root_cause': ok, 'lenient': ok, 'checks': checks, 'kind': 'healthy',
                'alerting': len(alerting), 'commit_expected': False}

    top = primary(alerting)
    checks['detected'] = top is not None
    checks['top service'] = bool(top) and names_service(_service_fields(top), answer['services'])
    checks['top cause'] = bool(top) and matches_cause(
        f"{top.get('root_cause') or ''} {top.get('description') or ''}", answer['cause'])
    if answer.get('blame_sha'):
        checks['top commit'] = bool(top) and blames(top, answer['blame_sha'])
    for sha in answer.get('wrong_shas') or []:
        checks[f'not blamed {sha[:7]}'] = not any(sha[:7] in _commits(i) for i in issues)
    checks['focused'] = len(alerting) <= answer.get('max_issues', 2)
    for decoy in answer.get('decoy_services') or []:
        checks[f'no critical on {decoy}'] = not any(
            _sev(i) == SEVERITY['CRITICAL'] and names_service(_service_fields(i), [decoy]) for i in issues)

    def full_text(i):
        return f"{i.get('description') or ''} {i.get('root_cause') or ''} {i.get('recommendation') or ''}"
    lenient = any(
        names_service(f"{full_text(i)} {_service_fields(i)}", answer['services'])
        and matches_cause(full_text(i), answer['cause']) for i in issues)

    root_cause = all(checks[k] for k in ('detected', 'top service', 'top cause', 'top commit') if k in checks)
    return {'verdict': all(checks.values()), 'root_cause': root_cause, 'lenient': lenient, 'checks': checks,
            'kind': 'incident',
            'alerting': len(alerting), 'commit_expected': bool(answer.get('blame_sha'))}
