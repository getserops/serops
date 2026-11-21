"""
Whether a reference shown on a page has something to open.

An analysis names traces and commits. The pages link a trace id to its
waterfall and a commit sha to the batch's code changes, and both links are
dead ends when the row is not there: a trace the store never received (it
came from an external trace store, or was dropped by retention), a commit
the analysis named that the batch holds no code change for. The API says
so next to each reference, and the frontend then shows plain text:

    span items      ``trace_stored``  a Trace row exists for ``trace_id``
    linked commits  ``in_batch``      the batch has a code change with that sha
"""

from traces.models import Trace


def stored_trace_ids(organisation_id, trace_ids):
    """The subset of ``trace_ids`` this organisation has a Trace row for."""
    wanted = {t for t in trace_ids if t}
    if not wanted or organisation_id is None:
        return set()
    return set(Trace.objects.filter(organisation_id=organisation_id, trace_id__in=wanted)
               .values_list('trace_id', flat=True))


def flag_trace_items(organisation_id, *item_lists):
    """Copies of the span items of each list, each with ``trace_stored``.
    One query for all of them; the stored items are not modified."""
    lists = [[i for i in (items or []) if isinstance(i, dict)] for items in item_lists]
    stored = stored_trace_ids(organisation_id, [i.get('trace_id') for items in lists for i in items])
    return [[dict(i, trace_stored=i.get('trace_id') in stored) for i in items] for items in lists]


def flag_batch_traces(batch, data):
    """``data`` (a batch's ``data``) with ``trace_stored`` on the span items
    of its trace snapshot. Returns ``data`` itself when it has no snapshot."""
    traces = data.get('traces') if isinstance(data, dict) else None
    if not isinstance(traces, dict):
        return data
    top_slow, top_errors = flag_trace_items(
        batch.organisation_id, traces.get('top_slow'), traces.get('top_errors'))
    return dict(data, traces=dict(traces, top_slow=top_slow, top_errors=top_errors))


def flag_timeline_events(batch, events):
    """Set ``detail.trace_stored`` on the timeline events that name a trace."""
    details = [e['detail'] for e in events
               if isinstance(e.get('detail'), dict) and e['detail'].get('trace_id')]
    stored = stored_trace_ids(batch.organisation_id, [d['trace_id'] for d in details])
    for detail in details:
        detail['trace_stored'] = detail['trace_id'] in stored
    return events


def batch_commit_shas(batch):
    """The shas of the code changes a batch holds, lower case."""
    data = getattr(batch, 'data', None)
    changes = data.get('code_changes') if isinstance(data, dict) else None
    return [str(c.get('sha') or '').lower() for c in changes or [] if isinstance(c, dict) and c.get('sha')]


def commit_in_batch(sha, batch_shas):
    """A linked commit and a code change are the same commit when one sha
    is a prefix of the other: analyses name short shas, stores full ones."""
    sha = str(sha or '').lower()
    return bool(sha) and any(known.startswith(sha) or sha.startswith(known) for known in batch_shas)
