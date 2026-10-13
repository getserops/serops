"""Gauntlet runner CLI.

Usage inside the backend container (or a transient one against the
same DB the celery worker sees):

    python -m tests_gauntlet.run_gauntlet --tier 0
    python -m tests_gauntlet.run_gauntlet --batch S1
    python -m tests_gauntlet.run_gauntlet --list

The runner discovers batch generators automatically: every module in
``tests_gauntlet/generators/`` that exposes ``BATCH_ID`` (short name),
``TIER`` (0-4), ``run(ctx)`` (returns real batch_id) and
``EXPECTATION`` (Expectation instance) is picked up.
"""

from __future__ import annotations

import argparse
import importlib
import pkgutil
import sys
import time
from dataclasses import dataclass
from typing import Callable

# Django must be set up before we import anything under it. Callers
# outside ``manage.py shell`` need this; harmless if already done.
# Defaults to prod settings on e2e; ``-e DJANGO_SETTINGS_MODULE=…``
# overrides for local test-DB runs.
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'api.settings')
import django
try:
    django.setup()
except Exception:
    pass

from tests_gauntlet import _core  # noqa: E402
from tests_gauntlet._core import (  # noqa: E402
    Expectation, GauntletContext, check_expectation, ensure_project,
    restore_default_provider, set_default_provider, wait_for_analysis,
)


@dataclass
class GauntletBatch:
    short_name: str      # e.g. 'S1'
    tier: int            # 0-4
    module_name: str
    run: Callable        # (ctx) -> real batch_id
    expectation: Expectation


def _discover_batches() -> list[GauntletBatch]:
    """Return every generator that opts in via the module contract."""
    from tests_gauntlet import generators
    batches: list[GauntletBatch] = []
    for _loader, mod_name, _is_pkg in pkgutil.iter_modules(generators.__path__):
        full = f'tests_gauntlet.generators.{mod_name}'
        mod = importlib.import_module(full)
        if not all(hasattr(mod, a) for a in ('BATCH_ID', 'TIER', 'run', 'EXPECTATION')):
            continue
        batches.append(GauntletBatch(
            short_name=mod.BATCH_ID,
            tier=int(mod.TIER),
            module_name=full,
            run=mod.run,
            expectation=mod.EXPECTATION,
        ))
    return sorted(batches, key=lambda b: (b.tier, b.short_name))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------

def _fmt_summary(s: dict) -> str:
    if not s.get('exists'):
        return f'batch never created (elapsed {s.get("elapsed_s", 0):.1f}s)'
    return (
        f'model={s.get("model_name") or "?":10s} '
        f'issues={s.get("issue_count") or 0:2d} '
        f'sentinel={s.get("sentinel_decision") or "?":<8s} '
        f'time={s.get("elapsed_s", 0):5.1f}s'
    )


def run_batch(batch: GauntletBatch, ctx: GauntletContext, timeout: float) -> tuple[bool, dict, list[str]]:
    """Execute one batch and evaluate its expectation. Returns (passed, summary, failures)."""
    real_batch_id = batch.run(ctx)
    summary = wait_for_analysis(real_batch_id, timeout=timeout)
    passed, fails = check_expectation(summary, batch.expectation)
    return passed, summary, fails


def main() -> int:
    parser = argparse.ArgumentParser(description='SerOps real-prod gauntlet runner')
    parser.add_argument('--tier', type=int, help='Run every batch in tier N (0-4)')
    parser.add_argument('--batch', help='Run one batch by short name (e.g. S1)')
    parser.add_argument('--list', action='store_true', help='List discovered batches')
    parser.add_argument('--timeout', type=float, default=180.0,
                        help='Per-batch analysis timeout in seconds')
    parser.add_argument('--dry-run', action='store_true',
                        help='List what would run without executing')
    args = parser.parse_args()

    all_batches = _discover_batches()
    if args.list:
        for b in all_batches:
            print(f'  T{b.tier}  {b.short_name:20s} ({b.module_name})')
        return 0

    if args.batch:
        selected = [b for b in all_batches if b.short_name == args.batch]
    elif args.tier is not None:
        selected = [b for b in all_batches if b.tier == args.tier]
    else:
        parser.print_help()
        return 2

    if not selected:
        print(f'No matching batches. Available: {[b.short_name for b in all_batches]}')
        return 3

    if args.dry_run:
        for b in selected:
            print(f'DRY  T{b.tier}  {b.short_name}')
        return 0

    ctx = GauntletContext()
    ensure_project(ctx)

    # Swap the org's default AI provider for the duration of the run
    # so the gauntlet always uses ``ctx.model`` regardless of the org's
    # user-visible preference. Restored on exit even if the run crashes.
    prev_provider = None
    try:
        prev_provider = set_default_provider(ctx.org_id, ctx.model)
    except Exception as e:
        print(f'!! Could not set default provider to {ctx.model!r}: {e}')
        print(f'!! Falling back to org default (whatever it is)')

    print(f'== Gauntlet run == org={ctx.org_id!r} project={ctx.project_name!r} '
          f'model={ctx.model!r} (was={prev_provider!r}) timeout={args.timeout}s')
    print(f'== {len(selected)} batches selected ==\n')

    try:
        results = []
        started_all = time.monotonic()
        for i, batch in enumerate(selected, 1):
            print(f'[{i}/{len(selected)}] T{batch.tier}  {batch.short_name} … ',
                  end='', flush=True)
            try:
                passed, summary, fails = run_batch(batch, ctx, args.timeout)
            except Exception as e:  # pragma: no cover — surface any generator crash
                passed, summary, fails = False, {}, [
                    f'generator crashed: {type(e).__name__}: {e}',
                ]

            results.append((batch, passed, summary, fails))
            mark = 'PASS' if passed else 'FAIL'
            print(f'{mark}  {_fmt_summary(summary)}')
            for f in fails:
                print(f'       └─ {f}')
    finally:
        restore_default_provider(ctx.org_id, prev_provider)

    total_s = time.monotonic() - started_all
    passed_n = sum(1 for _, p, _, _ in results if p)
    print()
    print(f'== {passed_n}/{len(results)} passed in {total_s:.1f}s (provider restored to {prev_provider!r}) ==')
    return 0 if passed_n == len(results) else 1


if __name__ == '__main__':
    sys.exit(main())
