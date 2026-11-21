"""
Reading the demo seed files (``Data/demo_seed/``) for ``seed_demo_org``.

The files are real analyses converted by ``tools/demo-seed/build_seed.py``
(format in ``tools/demo-seed/README.md``). This module reads them, moves
their times and works out what is shared between files: which issue rows are
one issue, which services a project has. It writes nothing to the database
and imports nothing from Django, so the same code produces
``replaced-values.json`` from the command line.

    python3 backend/Data/demo_seed_loader.py --write-replaced-values
"""

import gzip
import json
import os
from datetime import timedelta, timezone

try:
    from .demo_seed_time import parse_time, shift_times
except ImportError:  # run as a script
    from demo_seed_time import parse_time, shift_times

SEED_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'demo_seed')
SEED_SCHEMA = 'serops-demo-seed/1'
CHAT_SCHEMA = 'serops-demo-chat/1'
RESOLUTIONS_FILE = 'resolutions.json'
INTEGRATIONS_FILE = 'integrations.json'
REPLACED_VALUES_FILE = 'replaced-values.json'
CHAT_DIR = 'chat'

# The run-time values the owner's rule replaces on every issue.
ISSUE_STATE_FIELDS = ('created_at', 'last_seen_at', 'occurrence_count')


def _read_json(path):
    opener = gzip.open if path.endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as handle:
        return json.load(handle)


def load_index(seed_dir=SEED_DIR):
    return _read_json(os.path.join(seed_dir, 'index.json'))


def seed_id(file_name):
    """``fleet-K7-r1.json.gz`` -> ``fleet-K7-r1``: how a chat file names its analysis."""
    return file_name[:-len('.json.gz')] if file_name.endswith('.json.gz') else file_name


def stable_batch_id(name):
    """The batch id an analysis is loaded under: ``acme-fleet-k7-r1`` for the
    seed ``fleet-K7-r1``. The captured id holds the time of the analysis, so
    it would change with every time shift and break each link to a demo
    analysis; this one depends on the file name only."""
    return 'acme-' + name.lower()


def with_stable_batch_id(name, doc):
    """A copy of one seed document with its captured batch id replaced by
    the stable one, wherever a string of the loaded sections holds it."""
    captured, stable = doc['batch']['batch_id'], stable_batch_id(name)

    def rec(obj):
        if isinstance(obj, dict):
            return {(k.replace(captured, stable) if isinstance(k, str) else k): rec(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [rec(v) for v in obj]
        if isinstance(obj, str) and captured in obj:
            return obj.replace(captured, stable)
        return obj
    return rec(doc)


def load_seeds(seed_dir=SEED_DIR, index=None):
    """Every seed file of the index as ``(seed id, document)``, oldest analysis first."""
    index = index or load_index(seed_dir)
    seeds = []
    for entry in index['files']:
        doc = _read_json(os.path.join(seed_dir, entry['file']))
        if doc.get('schema') != SEED_SCHEMA:
            raise ValueError('%s: unknown seed schema %r' % (entry['file'], doc.get('schema')))
        seeds.append((seed_id(entry['file']), doc))
    seeds.sort(key=lambda item: (parse_time(item[1]['anchor']), item[0]))
    return seeds


def latest_time(seeds):
    """The last moment any seeded row is dated: the end of the newest analysis,
    its revert, or the last span stored after it."""
    moments = []
    for _, doc in seeds:
        batch, inv, injection = doc['batch'], doc.get('investigation') or {}, doc.get('injection') or {}
        moments += [batch.get('timestamp'), batch.get('analyzed_at'), inv.get('finished_at'),
                    injection.get('fault_reverted'), (injection.get('revert') or {}).get('at')]
        moments += [trace.get('end_time') for trace in (doc.get('traces') or {}).get('items') or []]
    return max(parse_time(m) for m in moments if m)


def whole_day_delta(seeds, now):
    """The one delta every analysis moves by: a whole number of days (the
    analysis texts name bare times of day, which stay true only then), chosen
    so the newest analysis falls on the day before ``now``. Yesterday is
    always in the past, whatever the time of day."""
    newest = latest_time(seeds).astimezone(timezone.utc).date()
    yesterday = now.astimezone(timezone.utc).date() - timedelta(days=1)
    return timedelta(days=(yesterday - newest).days)


def shift_seed(doc, delta, index):
    """A copy of one seed document with every time moved by ``delta``."""
    if not delta:
        return doc
    return shift_times(doc, delta.total_seconds(), index['time']['paths'], doc['anchor'])


def shift_iso(value, delta):
    """One ISO time moved by ``delta``, as an aware datetime."""
    return parse_time(value) + delta if value else None


def merge_issues(seeds):
    """The issues of all files as one entry per issue.

    SerOps deduplicates issues, so an issue raised by several of the seeded
    analyses is in several files under one ``capture_ref``, each time as that
    analysis left it. Returns, per issue and oldest sighting first::

        {'capture_ref': ..., 'sightings': [{'seed': seed id, 'incident': ..., 'issue': {...}}]}

    The row is loaded as its last sighting wrote it, which is how the product
    left it; the earlier sightings become occurrences.
    """
    merged = {}
    for name, doc in seeds:
        for issue in doc.get('issues') or []:
            entry = merged.setdefault(issue['capture_ref'], {'capture_ref': issue['capture_ref'], 'sightings': []})
            entry['sightings'].append({'seed': name, 'incident': doc['source']['incident'], 'issue': issue})
    return [merged[ref] for ref in sorted(merged, key=_ref_order)]


def _ref_order(capture_ref):
    estate, _, number = capture_ref.rpartition('-issue-')
    return (estate, int(number)) if number.isdigit() else (capture_ref, 0)


def first_seen(sighting, doc):
    """When this analysis wrote the issue. An issue the analysis created has
    that as ``created_at``; one it saw again has it as ``last_seen_at``."""
    issue = sighting['issue']
    if issue.get('created_at') and parse_time(issue['created_at']) >= parse_time(doc['anchor']):
        return issue['created_at']
    return issue['last_seen_at']


def replaced_values(seeds):
    """What the owner's rule replaces, per issue, with the run-time values it
    replaces. Times are the captured ones: no time in this file is shifted.

    Rule: ``occurrence_count`` is the number of seeded analyses that raised
    the issue, ``created_at`` the time the first of them wrote it,
    ``last_seen_at`` the time the last one did.
    """
    docs = dict(seeds)
    issues = []
    for entry in merge_issues(seeds):
        sightings = entry['sightings']
        first, last = sightings[0], sightings[-1]
        seeded = {
            'occurrence_count': len(sightings),
            'created_at': first_seen(first, docs[first['seed']]),
            'last_seen_at': last['issue']['last_seen_at'],
        }
        run_time = [dict({'seed': s['seed']}, **{f: s['issue'].get(f) for f in ISSUE_STATE_FIELDS})
                    for s in sightings]
        row = {
            'capture_ref': entry['capture_ref'],
            'component': last['issue'].get('component'),
            'seeds': [s['seed'] for s in sightings],
            'run_time': run_time,
            'seeded': seeded,
            'replaced': sorted(f for f in ISSUE_STATE_FIELDS
                               if any(r[f] != seeded[f] for r in run_time)),
        }
        incidents = sorted({s['incident'] for s in sightings})
        if len(incidents) > 1:
            row['note'] = ('SerOps attached analyses of different incidents (%s) to this one issue. '
                           'Kept as the product had it: one issue, loaded as its last analysis wrote it, '
                           'with one occurrence per analysis.' % ', '.join(incidents))
        issues.append(row)
    return {
        'rule': ('occurrence_count = number of seeded analyses that raised the issue; '
                 'created_at = when the earliest of them wrote it; '
                 'last_seen_at = when the latest of them wrote it'),
        'times': 'as captured (UTC), not shifted',
        'issues': issues,
        'batch_ids': {
            'rule': ('the captured batch id, which holds the time of the analysis, is replaced by a stable id '
                     'made from the seed file name, so a link to a demo analysis keeps working'),
            'stable_ids': {name + '.json.gz': stable_batch_id(name) for name in sorted(docs)},
        },
    }


def dump_replaced_values(seeds):
    return json.dumps(replaced_values(seeds), indent=1, sort_keys=True, ensure_ascii=False) + '\n'


def project_services(seeds):
    """``{project key: sorted service names}``: the services the analyses of a
    project name, in their logs, their issues and their trace snapshot."""
    services = {}
    for _, doc in seeds:
        names = services.setdefault(doc['project']['key'], set())
        data = doc['batch'].get('data') or {}
        for line in data.get('logs') or []:
            source = line.get('_source') or {}
            names.add(source.get('service_name') or source.get('service'))
        for issue in doc.get('issues') or []:
            names.add(issue.get('component'))
            names.update(issue.get('affected_services') or [])
        names.update((data.get('traces') or {}).get('services_touched') or [])
        names.update((doc.get('investigation') or {}).get('services') or [])
    return {key: sorted(n for n in names if n) for key, names in services.items()}


def requesters(seeds):
    """The people who started the seeded investigations, in order of first appearance."""
    names = []
    for _, doc in seeds:
        name = (doc.get('investigation') or {}).get('requested_by')
        if name and name not in names:
            names.append(name)
    return names


def load_resolutions(seed_dir=SEED_DIR):
    """``{capture_ref: entry}`` of the hand-written resolution notes."""
    return _read_json(os.path.join(seed_dir, RESOLUTIONS_FILE))['issues']


def load_integrations(seed_dir=SEED_DIR):
    """Per project key, the stores that environment had connected:
    ``{'observability': [...], 'delivery': [...]}``. Types and names
    only; the file holds no address and no credential."""
    return _read_json(os.path.join(seed_dir, INTEGRATIONS_FILE))['projects']


def load_chats(seed_dir=SEED_DIR):
    """The optional chat sessions, ``chat/*.json``, in file-name order.

    One file is one session::

        {"schema": "serops-demo-chat/1", "title": "...", "batch": "<seed id>",
         "model": "<model id>",
         "messages": [{"role": "user" | "assistant", "text": "...", "offset_seconds": 0}]}

    ``offset_seconds`` counts from the end of the linked analysis.
    """
    chat_dir = os.path.join(seed_dir, CHAT_DIR)
    if not os.path.isdir(chat_dir):
        return []
    chats = []
    for name in sorted(os.listdir(chat_dir)):
        if not name.endswith('.json'):
            continue
        chat = _read_json(os.path.join(chat_dir, name))
        if chat.get('schema') != CHAT_SCHEMA:
            raise ValueError('%s: unknown chat schema %r' % (name, chat.get('schema')))
        chats.append(chat)
    return chats


def chat_exchanges(chat):
    """The messages of one chat file as ``(question, answer, offset_seconds)``:
    a ChatMessage row holds a question and its answer."""
    exchanges, question = [], None
    for message in chat.get('messages') or []:
        if message.get('role') == 'user':
            if question is not None:
                exchanges.append((question['text'], '', question.get('offset_seconds', 0)))
            question = message
        elif message.get('role') == 'assistant':
            asked = question or {'text': '', 'offset_seconds': message.get('offset_seconds', 0)}
            exchanges.append((asked['text'], message['text'],
                              message.get('offset_seconds', asked.get('offset_seconds', 0))))
            question = None
    if question is not None:
        exchanges.append((question['text'], '', question.get('offset_seconds', 0)))
    return exchanges


if __name__ == '__main__':
    import sys
    if '--write-replaced-values' in sys.argv[1:]:
        with open(os.path.join(SEED_DIR, REPLACED_VALUES_FILE), 'w', encoding='utf-8') as out:
            out.write(dump_replaced_values(load_seeds()))
    else:
        sys.stdout.write(dump_replaced_values(load_seeds()))
