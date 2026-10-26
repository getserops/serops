"""Helpers to write incident data the way SerOps' batch analysis reads it.

A scenario is a dict:

  id, name, category
  set        'tuned' (the prompt rules were adjusted while these failed) or
             'held_out' (written and committed before any model run)
  data       the batch data: Elasticsearch-style logs, metrics summary,
             traces summary, CI jobs, code changes with unified diffs
  answer     the answer key, read by scoring.py:
    services       names that count as the right service (any of them)
    cause          groups of words; the top issue's root cause and
                   description must contain one word of every group
    blame_sha      the commit at fault, or None when no commit is
    wrong_shas     commits present as distractors that must not be blamed
    max_issues     most WARNING-or-worse issues for one root cause
    benign_max     for windows with nothing wrong: highest severity allowed
    decoy_services services with old, unrelated noise: no CRITICAL on them
"""
from datetime import datetime, timedelta, timezone

T0 = datetime(2026, 10, 18, 14, 0, tzinfo=timezone.utc)


def ts(minutes):
    return (T0 + timedelta(minutes=minutes)).isoformat().replace('+00:00', 'Z')


def log(minute, service, level, message, host='node-a', i=[0]):
    i[0] += 1
    return {'_id': f'log-{i[0]}', '_source': {
        '@timestamp': ts(minute), 'message': message, 'log_level': level,
        'service': {'name': service}, 'host': {'name': host},
        'environment': 'production'}}


def commit(sha, minute, author, message, files):
    adds = sum(f['diff'].count('\n+') for f in files)
    dels = sum(f['diff'].count('\n-') for f in files)
    return {'sha': sha, 'timestamp': ts(minute), 'author': author, 'branch': 'main',
            'message': message, 'service_name': None,
            'stats': {'files': len(files), 'additions': adds, 'deletions': dels},
            'files': files}


def filler(n, start, indent='    '):
    return '\n'.join(f' {indent}line_{start + k} = compute_{start + k}()' for k in range(n))


def stats(avg, peak, current, trend='STABLE'):
    return {'avg': avg, 'max': peak, 'current': current, 'trend': trend}


def answer(services, cause=(), blame_sha=None, wrong_shas=(), max_issues=2, benign_max=None,
           decoy_services=()):
    return {'services': list(services), 'cause': [list(g) for g in cause], 'blame_sha': blame_sha,
            'wrong_shas': list(wrong_shas), 'max_issues': max_issues, 'benign_max': benign_max,
            'decoy_services': list(decoy_services)}


UNRELATED_CSS = '\n'.join(['@@ -10,4 +10,6 @@ .btn {', ' color: #fff;', '+  border-radius: 8px;',
                           '+  padding: 6px 12px;', ' }'])
