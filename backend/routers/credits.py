from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend import credits as credits_svc
from backend.auth import get_current_user
from backend.database import get_db
from backend.models import CreditTransaction, User
from backend.schemas import CreditBalanceOut, CreditTransactionOut

router = APIRouter(prefix="/credits", tags=["credits"])


@router.get("/balance", response_model=CreditBalanceOut)
def get_balance(current_user: User = Depends(get_current_user)):
    return credits_svc.balance_info(current_user)


@router.get("/history", response_model=list[CreditTransactionOut])
def get_history(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return (
        db.query(CreditTransaction)
        .filter(CreditTransaction.user_id == current_user.id)
        .order_by(CreditTransaction.created_at.desc())
        .limit(100)
        .all()
    )
