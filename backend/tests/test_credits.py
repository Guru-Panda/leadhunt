"""Credit metering tests (isolated in-memory DB, both billing modes)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend import credits as c
from backend.config import settings
from backend.database import Base
from backend.models import CreditTransaction, User


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def user(db):
    u = User(email="t@example.com", credits=10)
    db.add(u)
    db.commit()
    db.refresh(u)
    return u


def test_test_mode_charges_zero(db, user):
    settings.BILLING_ENABLED = False
    charged = c.charge(db, user, 5, "unlock_contact", 1)
    assert charged == 0
    assert user.credits == 10  # nothing deducted
    tx = db.query(CreditTransaction).first()
    assert tx.amount == 0 and "would cost 5" in (tx.note or "")


def test_live_mode_deducts(db, user):
    settings.BILLING_ENABLED = True
    try:
        charged = c.charge(db, user, 4, "unlock_contact", 1)
        assert charged == 4
        assert user.credits == 6
    finally:
        settings.BILLING_ENABLED = False


def test_insufficient_raises(db, user):
    settings.BILLING_ENABLED = True
    try:
        with pytest.raises(c.InsufficientCredits):
            c.charge(db, user, 999, "unlock_contact", 1)
        assert user.credits == 10  # unchanged on failure
    finally:
        settings.BILLING_ENABLED = False


def test_grant_adds_credits(db, user):
    assert c.grant(db, user, 50, "topup") == 60
    assert user.credits == 60


def test_balance_info_shape(user):
    info = c.balance_info(user)
    assert set(info) == {"credits", "billing_enabled", "cost_unlock", "cost_export"}
