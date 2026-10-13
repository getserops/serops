"""AI cost budget tracking + enforcement (Q3.3).

Enterprises need a hard cap on AI spend per org so a runaway
correlation loop / flaky retry / hostile actor can't burn through
$50K in a night. This module provides:

* ``BudgetTracker.current_month_spend(org)`` — sum of
  ``AITokenUsage.cost_usd`` for the calendar month.
* ``BudgetTracker.check_budget(org, estimated_cost)`` — cheap
  pre-flight before dispatching an AI call. Returns
  ``BudgetCheck(ok, current, remaining, budget)``.
* ``BudgetExceeded`` — raised by
  ``ai_service.generate_for_organisation`` when the pre-flight
  refuses. Batch pipeline catches, marks ``batch.ai_skipped=True``
  with a clear reason, and rule-based issue creation (Sentinel,
  correlation engine) still runs so users don't lose incidents.

Design notes:

* **Calendar month**, not rolling 30 days. Matches how CFOs actually
  budget ("we said $2K/month for AI spend"). Enforcement resets
  automatically on the 1st.
* **Advisory pre-flight**. We don't know the exact cost of a call
  until it completes, so ``check_budget`` uses an *estimated* cost
  and errs on the side of "let it through if we're comfortably
  under, block if we're near the ceiling." A single call slightly
  over the cap is fine; the next one blocks.
* **Fail-open on tracker errors**. If the DB query for current
  spend fails, we let the AI call proceed rather than starve the
  batch pipeline. Cost visibility is an observability concern; a
  broken observer must not break the primary function.
* **Zero-cost path for unlimited orgs**. When
  ``monthly_budget_usd`` is NULL (the default), ``check_budget``
  short-circuits with ``ok=True`` before querying — no DB round-trip.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional

from django.db.models import Sum
from django.utils import timezone

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised by generate_for_organisation when the pre-flight refuses.

    Callers (batch pipeline, chat view) should catch this specifically
    and degrade cleanly (skip AI, still create rule-based issues,
    show a friendly banner) rather than surface a generic 500.
    """

    def __init__(self, current: Decimal, budget: Decimal, org_id):
        self.current = current
        self.budget = budget
        self.org_id = org_id
        super().__init__(
            f'AI monthly budget exceeded for org={org_id}: '
            f'spent ${current:.2f} of ${budget:.2f}'
        )


@dataclass
class BudgetCheck:
    ok: bool
    current: Decimal           # what's been spent so far this month
    remaining: Optional[Decimal]   # None when budget is unlimited
    budget: Optional[Decimal]      # None when unlimited


class BudgetTracker:
    """Static helpers — no state beyond the calling context."""

    @staticmethod
    def _month_start(now: Optional[datetime] = None) -> datetime:
        """UTC start of the current calendar month."""
        now = now or timezone.now()
        return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    @classmethod
    def current_month_spend(cls, organisation) -> Decimal:
        """Sum of ``AITokenUsage.cost_usd`` for the current calendar month.

        Returns ``Decimal('0')`` on any DB error — cost visibility must
        never block AI calls.
        """
        try:
            from ai_model.models import AITokenUsage
            total = (
                AITokenUsage.objects
                .filter(
                    organisation=organisation,
                    timestamp__gte=cls._month_start(),
                )
                .aggregate(total=Sum('cost_usd'))
                .get('total')
            )
            return total or Decimal('0')
        except Exception as exc:
            logger.warning(
                'BudgetTracker.current_month_spend failed for org=%s: %s',
                getattr(organisation, 'id', '?'), exc,
            )
            return Decimal('0')

    @classmethod
    def check_budget(cls, organisation, estimated_cost: Decimal = Decimal('0')) -> BudgetCheck:
        """Pre-flight before an AI call. Cheap when budget is unlimited."""
        settings = cls._settings_for(organisation)
        budget = getattr(settings, 'monthly_budget_usd', None) if settings else None
        if budget is None:
            return BudgetCheck(ok=True, current=Decimal('0'), remaining=None, budget=None)

        current = cls.current_month_spend(organisation)
        projected = current + (estimated_cost or Decimal('0'))
        ok = projected <= budget
        remaining = budget - current
        return BudgetCheck(
            ok=ok, current=current, remaining=remaining, budget=budget,
        )

    @classmethod
    def enforce(cls, organisation, estimated_cost: Decimal = Decimal('0')) -> None:
        """Raise ``BudgetExceeded`` if the pre-flight fails.

        Callers that want a soft check should use ``check_budget``
        directly and read ``ok`` + ``remaining``.
        """
        result = cls.check_budget(organisation, estimated_cost)
        if not result.ok:
            raise BudgetExceeded(
                current=result.current,
                budget=result.budget or Decimal('0'),
                org_id=getattr(organisation, 'id', None),
            )

    @classmethod
    def is_warning(cls, organisation) -> bool:
        """True when current spend crossed the warn threshold.

        Used by the settings UI + logs to nudge admins before they
        hit the hard cap. Silent when no budget is set.
        """
        settings = cls._settings_for(organisation)
        budget = getattr(settings, 'monthly_budget_usd', None) if settings else None
        if budget is None or budget == 0:
            return False
        warn_pct = getattr(settings, 'budget_warn_pct', 80) or 80
        threshold = budget * Decimal(warn_pct) / Decimal(100)
        return cls.current_month_spend(organisation) >= threshold

    @staticmethod
    def _settings_for(organisation):
        try:
            from org_settings.models import OrganisationAISettings
            return OrganisationAISettings.objects.filter(
                organisation=organisation,
            ).first()
        except Exception:
            return None
