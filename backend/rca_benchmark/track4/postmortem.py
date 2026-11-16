"""
Twenty post-mortem drafts (``ai_model.postmortem.generate_postmortem_draft``)
for analysed scenarios.

Pre-registered (phase 3, 2026-11-16).

Deterministic checks: the AI wrote the draft (not the template fallback),
the cause matches the scenario's key, the service is named, the blamed commit
is named when the key has one, no personal data or injected text. The judge
grades what words cannot: the timeline is right and every claim can be traced
to the batch's evidence (no invented events, figures, people or fixes).
"""
from ..scoring import matches_cause, names_service

SCENARIOS = [
    'v01_deadlock', 'v03_thread_pool', 'v04_fd_exhaustion', 'v07_image_pull_auth', 'v10_oauth_secret_expired',
    'v13_cache_flush_stampede', 'v14_contract_break', 'v17_runtime_dependency_bump', 'v21_french_logs',
    'v25_pii_in_logs', 'v31_two_causes', 'w02_jvm_gc_pauses', 'w11_dlq_visibility_timeout',
    'w13_rds_failover_storm', 'w14_cron_overlap', 'w16_credential_stuffing', 'w22_pool_starved_by_slow_call',
    'w24_kill_switch_side_effect', 'w28_token_clock_bug', 'w35_alert_injection_and_pii',
]

def check_draft(markdown, answer, used_ai):
    low = str(markdown or '').lower()
    checks = {
        'written by the AI': used_ai,
        'names the service': names_service(low, answer['services']),
        'cause matches the key': matches_cause(low, answer['cause']),
    }
    if answer.get('blame_sha'):
        checks[f"names commit {answer['blame_sha'][:7]}"] = answer['blame_sha'][:7].lower() in low
    for sha in answer.get('wrong_shas') or []:
        # Mentioning a distractor is fine; calling it the cause is not.
        checks[f'does not blame {sha[:7]}'] = not any(
            f'{sha[:7]}{w}' in low or f'{w}{sha[:7]}' in low
            for w in (' caused', ' introduced', ' is the root', 'root cause: ', 'caused by commit ', 'caused by '))
    for text in answer.get('forbidden_text') or []:
        checks[f'no {text[:20]!r}'] = text.lower() not in low
    return {'checks': checks, 'pass': all(checks.values())}


assert len(SCENARIOS) == 20 and len(set(SCENARIOS)) == 20
