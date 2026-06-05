"""Credit accounting for the pay-per-use model.

Browsing/scoring leads is free; spending credits only happens on premium actions
(unlocking a verified contact, exporting). A `BILLING_ENABLED` flag lets the whole
flow run for free during testing while still recording an append-only ledger of
what each action WOULD cost — flip the flag to charge for real.
"""
from __future__ import annotations

import logging

from sqlalchemy.orm import Session

from backend.config import settings
from backend.models import CreditTransaction, User

log = logging.getLogger(__name__)


class InsufficientCredits(Exception):
    def __init__(self, needed: int, have: int):
        self.needed = needed
        self.have = have
        super().__init__(f"Need {needed} credits, have {have}")


def _record(db: Session, user: User, amount: int, action: str,
            lead_id: int | None, note: str | None) -> None:
    db.add(CreditTransaction(
        user_id=user.id, amount=amount, action=action, lead_id=lead_id,
        balance_after=user.credits or 0, note=note,
    ))


def grant(db: Session, user: User, amount: int, note: str = "grant") -> int:
    """Add credits to a user's balance. Returns the new balance."""
    user.credits = (user.credits or 0) + amount
    _record(db, user, amount, "grant", None, note)
    db.commit()
    return user.credits


def charge(db: Session, user: User, cost: int, action: str, lead_id: int | None = None) -> int:
    """Charge `cost` credits for an action. Returns the amount actually charged.

    Test mode (BILLING_ENABLED=False): records a 0-amount ledger entry noting the
    would-be cost and returns 0 (nothing deducted) — so the flow is free to test.
    Live mode: raises InsufficientCredits if the balance is too low; else deducts.
    """
    if not settings.BILLING_ENABLED:
        _record(db, user, 0, action, lead_id, note=f"test-mode (would cost {cost})")
        db.commit()
        return 0

    have = user.credits or 0
    if have < cost:
        raise InsufficientCredits(cost, have)
    user.credits = have - cost
    _record(db, user, -cost, action, lead_id, note=action)
    db.commit()
    return cost


def balance_info(user: User) -> dict:
    return {
        "credits": user.credits or 0,
        "billing_enabled": settings.BILLING_ENABLED,
        "cost_unlock": settings.CREDIT_COST_UNLOCK,
        "cost_export": settings.CREDIT_COST_EXPORT,
    }
