"""Feedback learning — profile computation, bounded scoring nudge, source reorder."""
from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models import Lead, Strategy, User
from backend.pipeline import learning


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


def _lead(db, strategy, **kw):
    base = dict(
        user_id=strategy.user_id, strategy_id=strategy.id, source="reddit",
        external_id=kw.pop("ext", "x"), person_name="N", intent_signals=[],
    )
    base.update(kw)
    l = Lead(**base)
    db.add(l); db.commit()
    return l


def test_too_few_ratings_is_neutral(db, strategy):
    _lead(db, strategy, ext="1", feedback=1, source_snippet="fintech compliance")
    prof = learning.compute_learning_profile(strategy, db)
    assert prof.get("n_approved") == 1
    assert "liked_terms" not in prof  # not enough signal yet
    assert learning.score_adjustment({"source_snippet": "fintech"}, prof) == 0.0


def test_learns_liked_and_disliked_terms(db, strategy):
    # Approve fintech leads, reject crypto leads.
    for i in range(3):
        _lead(db, strategy, ext=f"a{i}", feedback=1, source="reddit",
              source_snippet="fintech compliance reporting platform")
    for i in range(3):
        _lead(db, strategy, ext=f"r{i}", feedback=-1, source="github",
              source_snippet="crypto token airdrop blockchain")

    prof = learning.compute_learning_profile(strategy, db)
    assert prof["n_approved"] == 3 and prof["n_rejected"] == 3
    assert "fintech" in prof["liked_terms"]
    assert "crypto" in prof["disliked_terms"]
    assert "reddit" in prof["liked_sources"]
    assert "github" in prof["disliked_sources"]

    # A fintech lead gets nudged up; a crypto lead nudged down — both bounded.
    up = learning.score_adjustment({"source_snippet": "fintech compliance", "source": "reddit"}, prof)
    down = learning.score_adjustment({"source_snippet": "crypto airdrop", "source": "github"}, prof)
    assert 0 < up <= learning.MAX_ADJUSTMENT
    assert -learning.MAX_ADJUSTMENT <= down < 0


def test_adjustment_is_bounded(db, strategy):
    prof = {
        "n_approved": 5, "n_rejected": 5,
        "disliked_terms": [f"bad{i}" for i in range(20)],
        "disliked_sources": ["github"], "disliked_signals": ["x"],
    }
    blob = " ".join(f"bad{i}" for i in range(20))
    delta = learning.score_adjustment(
        {"source_snippet": blob, "source": "github", "intent_signals": ["x"]}, prof)
    assert delta == -learning.MAX_ADJUSTMENT  # clamped, never runs away


def test_source_reorder_floats_liked_demotes_disliked():
    prof = {"liked_sources": ["reddit"], "disliked_sources": ["github"]}
    out = learning.apply_source_preferences(["github", "apollo", "reddit", "bing"], prof)
    assert out[0] == "reddit"          # liked first
    assert out[-1] == "github"         # disliked last
    assert set(out) == {"github", "apollo", "reddit", "bing"}  # nothing dropped


def test_update_persists_profile(db, strategy):
    for i in range(3):
        _lead(db, strategy, ext=f"a{i}", feedback=1, source_snippet="fintech compliance")
    for i in range(2):
        _lead(db, strategy, ext=f"r{i}", feedback=-1, source_snippet="crypto airdrop")
    prof = learning.update_learning_profile(strategy, db)
    assert strategy.learning_profile == prof
    assert prof["n_approved"] == 3
