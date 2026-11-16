"""
A fair share of the log sample for every service in a batch.

Two faults at once on different services (phase 3 client C3, K12): one
service logged ~3,700 errors and took every slot of the analysis sample, and
the other service's real warnings never reached the AI, which then guessed
that second cause. The sample size does not change; each service with errors
or warnings is guaranteed a few slots before the loudest one takes the rest.
"""
import logging
from dataclasses import replace

logger = logging.getLogger(__name__)

# Slots each service is guaranteed, at most (fewer when many services share
# a small sample: never more than half the sample goes to guarantees).
FLOOR_PER_SERVICE = 5

# Extra store reads when the main read hit its cap: at most this many
# services, this many records each.
TOP_UP_MAX_SERVICES = 8
TOP_UP_RECORDS = 200


def fair_share(items, key, cap, floor=FLOOR_PER_SERVICE):
    """At most ``cap`` of ``items`` (already in priority order), each value
    of ``key(item)`` guaranteed ``floor`` of them first, the rest by
    priority. The kept items keep their order."""
    items = list(items)
    if cap is None or len(items) <= cap:
        return items
    if cap <= 0:
        return []
    groups = {}
    for i, item in enumerate(items):
        groups.setdefault(key(item) or '', []).append(i)
    if len(groups) <= 1:
        return items[:cap]
    per = max(1, min(floor, cap // (2 * len(groups))))
    chosen = set()
    # Guarantees first, quietest services first so a tie never drops them.
    for indices in sorted(groups.values(), key=len):
        for i in indices[:per]:
            if len(chosen) >= cap:
                break
            chosen.add(i)
    for i in range(len(items)):
        if len(chosen) >= cap:
            break
        chosen.add(i)
    return [items[i] for i in sorted(chosen)]


def top_up_quiet_services(provider, index_pattern, log_query, logs, service_names, service_of):
    """When the main read came back full (``max_results`` records, newest
    first), a quiet service's lines may have been cut by a loud one. Read
    each registered service that is missing from the result on its own,
    with a small cap. Returns the extra records; never raises."""
    cap = getattr(log_query, 'max_results', None)
    if not cap or len(logs) < cap or not service_names:
        return []
    present = {(service_of(log) or '').lower() for log in logs}
    missing = sorted({n for n in service_names if n and n.lower() not in present}, key=str.lower)
    extra, seen = [], set()
    for name in missing[:TOP_UP_MAX_SERVICES]:
        try:
            query = replace(log_query, services=[name], max_results=TOP_UP_RECORDS)
            found = list(provider.search(index_pattern, query) or [])
        except Exception as e:
            logger.warning(f"Log top-up for service {name!r} failed: {e}")
            continue
        for log in found:
            ident = getattr(log, 'raw_id', None) or id(log)
            if ident in seen:
                continue
            seen.add(ident)
            extra.append(log)
    if extra:
        logger.info(f"Log read hit its cap ({cap}); topped up {len(extra)} records from "
                    f"{min(len(missing), TOP_UP_MAX_SERVICES)} quiet service(s)")
    return extra
