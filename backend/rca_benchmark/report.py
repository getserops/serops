"""Summary numbers and a Markdown report from runner results."""
from collections import defaultdict

from .scoring import primary


def _pct(n, d):
    return f'{n}/{d} ({round(100 * n / d)}%)' if d else '–'


def summarise(results):
    """Per set ('tuned', 'held_out', 'all'): counts the report shows."""
    out = {}
    for name in ('held_out', 'tuned', 'all'):
        rows = [r for r in results if name == 'all' or r['set'] == name]
        if not rows:
            continue
        # Runs with no analysis (provider error, quota) are counted apart:
        # they say nothing about accuracy either way.
        scored = [r for r in rows if r['score']]
        incidents = [r for r in scored if r['answer'].get('benign_max') is None]
        healthy = [r for r in scored if r['answer'].get('benign_max') is not None]
        ok = lambda r, key: bool(r['score'] and r['score'][key])  # noqa: E731
        with_commit = [r for r in incidents if r['answer'].get('blame_sha')]
        out[name] = {
            'runs': len(rows),
            'incidents': len(incidents),
            'root_cause': sum(ok(r, 'root_cause') for r in incidents),
            'strict': sum(ok(r, 'verdict') for r in incidents),
            'lenient': sum(ok(r, 'lenient') for r in incidents),
            'commit_expected': len(with_commit),
            'commit_correct': sum(bool(r['score'] and r['score']['checks'].get('top commit')) for r in with_commit),
            'distractor_blamed': sum(any(
                not v for k, v in r['score']['checks'].items() if k.startswith('not blamed')) for r in scored),
            'healthy': len(healthy),
            'healthy_silent': sum(ok(r, 'verdict') for r in healthy),
            'mean_alerting': round(sum(r['score']['alerting'] for r in incidents) / max(1, len(incidents)), 2),
            'errors': sum(1 for r in rows if r['error']),
            'cost_usd': round(sum(r['cost_usd'] for r in rows), 4),
            'mean_seconds': round(sum(r['seconds'] for r in rows) / len(rows), 1),
        }
    by_id = defaultdict(list)
    for r in results:
        by_id[r['id']].append(bool(r['score'] and r['score']['root_cause']))
    repeated = [v for v in by_id.values() if len(v) > 1]
    if repeated:
        out['consistency'] = {'scenarios': len(repeated), 'stable': sum(len(set(v)) == 1 for v in repeated)}
    return out


def _excerpt(text, n=220):
    text = ' '.join(str(text or '').split())
    return text if len(text) <= n else text[:n - 1] + '…'


def markdown(results, meta, stopped=None):
    s = summarise(results)
    lines = [f"# SerOps RCA benchmark — {meta['provider']} ({meta['model']})", '',
             f"SerOps {meta['version']} (`{meta['commit']}`), run {meta['date']}, "
             f"{meta['rounds']} round(s), {len(results)} scenario runs.", '']
    if stopped:
        lines += [f'**Stopped early:** {stopped}.', '']
    labels = [('Root cause correct (top issue: service, cause, commit)', lambda x: _pct(x['root_cause'], x['incidents'])),
              ('All checks (also: no distractor blamed, at most 2 issues)', lambda x: _pct(x['strict'], x['incidents'])),
              ('Lenient (October 2026 rule: any issue mentions it)', lambda x: _pct(x['lenient'], x['incidents'])),
              ('Commit at fault named on the top issue', lambda x: _pct(x['commit_correct'], x['commit_expected'])),
              ('Runs that blamed a distractor commit', lambda x: str(x['distractor_blamed'])),
              ('Healthy windows left quiet', lambda x: _pct(x['healthy_silent'], x['healthy'])),
              ('Warning-or-worse issues per incident (1 is ideal)', lambda x: str(x['mean_alerting'])),
              ('Not analysed (provider error or quota; left out above)', lambda x: str(x['errors'])),
              ('AI cost (USD, from SerOps usage records)', lambda x: f"${x['cost_usd']}"),
              ('Mean time per analysis (s)', lambda x: str(x['mean_seconds']))]
    sets = [k for k in ('held_out', 'tuned', 'all') if k in s]
    titles = {'held_out': 'Held-out', 'tuned': 'Tuned', 'all': 'All'}
    lines += ['| | ' + ' | '.join(titles[k] for k in sets) + ' |', '|---|' + '---|' * len(sets)]
    for label, fn in labels:
        lines.append(f'| {label} | ' + ' | '.join(fn(s[k]) for k in sets) + ' |')
    if 'consistency' in s:
        c = s['consistency']
        lines += ['', f"Same root-cause verdict in every round: {_pct(c['stable'], c['scenarios'])} of scenarios."]
    lines += ['', '**Held-out** incidents were committed before any model run and no prompt rule was changed for '
              'them. **Tuned** incidents were used while fixing the prompt, so they guard against regressions '
              'and are not evidence of accuracy.', '', '## Scenarios', '',
              '| Scenario | Set | Kind | Root cause | All checks | Failed checks | Issues | Cost | s |',
              '|---|---|---|---|---|---|---|---|---|']
    mark = {True: 'yes', False: '**no**', None: 'error'}
    for r in results:
        sc = r['score']
        failed = ', '.join(k for k, v in sc['checks'].items() if not v) if sc else _excerpt(r['error'], 80)
        lines.append(f"| {r['id']}" + (f" (round {r['round']})" if meta['rounds'] > 1 else '')
                     + f" — {r['name']} | {r['set']} | {r['category']} | {mark[sc['root_cause'] if sc else None]} "
                     f"| {mark[sc['verdict'] if sc else None]} | {failed or '–'} | {len(r['issues'])} "
                     f"| ${r['cost_usd']} | {r['seconds']} |")
    failures = [r for r in results if not (r['score'] and r['score']['verdict'])]
    lines += ['', '## What SerOps said when a check failed', '']
    if not failures:
        lines.append('Nothing failed.')
    for r in failures:
        a = r['answer']
        lines += [f"### {r['id']} — {r['name']}", '']
        if a.get('benign_max'):
            lines.append(f"Expected: nothing worse than {a['benign_max']}.")
        else:
            lines.append(f"Expected: {' / '.join(a['services'])}; cause words "
                         + '; '.join('(' + ' | '.join(g) + ')' for g in a['cause'])
                         + (f"; commit {a['blame_sha'][:7]}" if a.get('blame_sha') else '; no commit at fault') + '.')
        if r['error']:
            lines.append(f"Error: {_excerpt(r['error'])}")
        top = primary([i for i in r['issues'] if i['severity'] in ('WARNING', 'CRITICAL')]) or primary(r['issues'])
        for i in r['issues']:
            lines.append(f"- {'**top** ' if i is top else ''}[{i['severity']}/{i['confidence']}] "
                         f"`{i['component']}` {('(+ ' + ', '.join(i['affected_services']) + ') ') if i['affected_services'] else ''}"
                         f"— {_excerpt(i['root_cause'] or i['description'])}"
                         + (f" (commits: {i['linked_commits']})" if i['linked_commits'] else ''))
        if not r['issues'] and not r['error']:
            lines.append('- no issue created')
        lines.append('')
    return '\n'.join(lines) + '\n'
