"""Lead purge scopes — 'unwanted' (rejected only) vs 'unapproved' (all but approved)."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Lead, Strategy, User
from backend.routers.leads import _purge_query


@pytest.fixture
def db():
    eng = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(eng)
    s = sessionmaker(bind=eng)()
    yield s
    s.close()


@pytest.fixture
def strategy(db):
    u = User(email="t@example.com")
    db.add(u); db.commit(); db.refresh(u)
    s = Strategy(user_id=u.id, title="t", main_problem="p", ideal_customer="c")
    db.add(s); db.commit(); db.refresh(s)
    return s


def _seed(db, strategy):
    rows = [
        ("new", None),         # untouched
        ("new", None),
        ("rejected", -1),      # disliked
        ("qualified", 1),      # approved
        ("contacted", None),   # approved (forward status)
        ("ignored", None),     # not approved
    ]
    for i, (status, fb) in enumerate(rows):
        db.add(Lead(user_id=strategy.user_id, strategy_id=strategy.id, source="reddit",
                    external_id=f"e{i}", person_name="N", status=status, feedback=fb))
    db.commit()


def test_unwanted_scope_only_removes_rejected(db, strategy):
    _seed(db, strategy)
    n = _purge_query(db, strategy.user_id, strategy.id, "unwanted").count()
    assert n == 1  # only the rejected/disliked one


def test_unapproved_scope_keeps_only_approved(db, strategy):
    _seed(db, strategy)
    deleted = _purge_query(db, strategy.user_id, strategy.id, "unapproved").delete(synchronize_session=False)
    db.commit()
    assert deleted == 4  # 2 new + 1 rejected + 1 ignored
    remaining = db.query(Lead).filter(Lead.strategy_id == strategy.id).all()
    assert {l.status for l in remaining} == {"qualified", "contacted"}


def test_unapproved_handles_null_feedback_and_status(db, strategy):
    # A bare 'new' lead with NULL feedback must still be deleted (no SQL-NULL leak).
    db.add(Lead(user_id=strategy.user_id, strategy_id=strategy.id, source="bing",
                external_id="bare", person_name="N", status="new"))
    db.commit()
    deleted = _purge_query(db, strategy.user_id, strategy.id, "unapproved").delete(synchronize_session=False)
    db.commit()
    assert deleted == 1
