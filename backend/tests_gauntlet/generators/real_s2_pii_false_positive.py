"""S2 · PII false positive.

Values that LOOK like PII to a naive regex but are actionable business
data: 9-digit customer IDs (look like SSNs), 16-digit order IDs (look
like PANs), machine ID / license key formats.

Over-redaction destroys actionability — the RCA must still name the
customer id or order id at least once, otherwise ops can't triage.
"""

from __future__ import annotations
from datetime import datetime, timedelta, timezone

from tests_gauntlet._core import Expectation

BATCH_ID = 'S2'
TIER = 0


# These MUST survive to the analysis output — they identify the incident.
CUSTOMER_ID = 'cust-874321905'          # 9 digits like SSN but with prefix
ORDER_ID = 'ord-4823910275640392'        # 16 digits like PAN but with prefix
LICENSE_KEY = 'LIC-2026-QRTY-8471-ACME'  # dash-separated but not a PAN


def _t(minutes_ago: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


def _log(level: str, msg: str, minutes_ago: int = 0) -> dict:
    return {
        'timestamp': _t(minutes_ago),
        '@timestamp': _t(minutes_ago),
        'level': level,
        'log_level': level,
        'message': msg,
        'service_name': 'checkout',
        'organisation_name': 'Acme Cloud',
        'project_name': 'gauntlet-checkout',
        'environment': 'production',
    }


def run(ctx):
    from tests_gauntlet._core import create_batch

    logs = [
        _log('INFO',  f'checkout requested by customer {CUSTOMER_ID} for order {ORDER_ID}', 6),
        _log('INFO',  f'license validation started for {LICENSE_KEY}', 5),
        _log('ERROR', f'inventory API 500 for order {ORDER_ID}: SKU-ABC-7712 not found in warehouse index', 4),
        _log('ERROR', f'checkout retry #2 failed for customer {CUSTOMER_ID} order {ORDER_ID}', 3),
        _log('ERROR', f'inventory API 500 again: warehouse index snapshot is 4h stale', 2),
        _log('ERROR', f'customer {CUSTOMER_ID} abandoned cart after 3 failures', 1),
    ]

    return create_batch(
        ctx,
        short_name=BATCH_ID.lower(),
        logs=logs,
    )


EXPECTATION = Expectation(
    min_issues=1,
    # The root cause must NAME the inventory / warehouse layer OR
    # reference the specific order id or customer id — otherwise
    # redaction ate the actionability.
    root_cause_contains=['inventory'],
    timed_out_ok=False,
)
