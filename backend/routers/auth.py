from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend import auth as auth_utils
from backend.config import settings
from backend.database import get_db
from backend.email_service import send_otp_email
from backend.models import EmailOTP, User
from backend.schemas import (
    LoginRequest,
    OTPLoginRequest,
    OTPVerifyRequest,
    RefreshRequest,
    SignupRequest,
    TokenResponse,
    UserOut,
    UserUpdate,
)

log = logging.getLogger(__name__)
router = APIRouter(prefix="/auth", tags=["auth"])

OTP_TTL_MINUTES = 10


async def _send_fresh_otp(email: str, db: Session) -> str:
    """Generate + persist + send an OTP. Returns the code (for dev fallback)."""
    code = EmailOTP.generate_code()
    expires = datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
    otp = EmailOTP(email=email, otp_code=code, expires_at=expires)
    db.add(otp)
    db.commit()
    await send_otp_email(email, code)
    return code


def _otp_response(detail: str, code: str) -> dict:
    body: dict = {"detail": detail}
    if settings.DEV_MODE:
        # Surface the code in the response so devs can complete signup
        # without configuring SMTP. Frontend should display this prominently.
        body["dev_otp"] = code
    return body


@router.post("/signup", status_code=202)
async def signup(body: SignupRequest, db: Session = Depends(get_db)):
    """Step 1: Enter email → receive OTP."""
    existing = db.query(User).filter(User.email == body.email).first()
    if existing and existing.is_verified:
        raise HTTPException(status_code=409, detail="Email already registered. Please log in.")
    if not existing:
        user = User(email=body.email)
        db.add(user)
        db.commit()
    code = await _send_fresh_otp(body.email, db)
    return _otp_response("OTP sent. Check your email.", code)


@router.post("/verify-otp", response_model=TokenResponse)
async def verify_otp(body: OTPVerifyRequest, db: Session = Depends(get_db)):
    """Step 2: Verify OTP → issue tokens. Optionally set password."""
    now = datetime.now(timezone.utc)
    otp = (
        db.query(EmailOTP)
        .filter(
            EmailOTP.email == body.email,
            EmailOTP.otp_code == body.otp_code,
            EmailOTP.used.is_(False),
            EmailOTP.expires_at > now,
        )
        .order_by(EmailOTP.created_at.desc())
        .first()
    )
    if not otp:
        raise HTTPException(status_code=400, detail="Invalid or expired OTP.")

    otp.used = True
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found.")
    user.is_verified = True
    if body.password:
        user.hashed_password = auth_utils.hash_password(body.password)
    db.commit()

    return TokenResponse(
        access_token=auth_utils.create_access_token(user.id),
        refresh_token=auth_utils.create_refresh_token(user.id),
    )


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: Session = Depends(get_db)):
    """Login with password OR request OTP if no password provided."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user or not user.is_verified:
        raise HTTPException(status_code=401, detail="Invalid credentials.")

    if body.password:
        if not user.hashed_password or not auth_utils.verify_password(body.password, user.hashed_password):
            raise HTTPException(status_code=401, detail="Invalid credentials.")
        return TokenResponse(
            access_token=auth_utils.create_access_token(user.id),
            refresh_token=auth_utils.create_refresh_token(user.id),
        )

    # No password → send OTP
    code = await _send_fresh_otp(body.email, db)
    return _otp_response("OTP sent. Check your email.", code)


@router.post("/request-otp", status_code=202)
async def request_otp(body: OTPLoginRequest, db: Session = Depends(get_db)):
    """Explicitly request OTP for passwordless login."""
    user = db.query(User).filter(User.email == body.email).first()
    if not user:
        # Don't reveal if email exists
        return {"detail": "If that email is registered, an OTP was sent."}
    code = await _send_fresh_otp(body.email, db)
    return _otp_response("OTP sent. Check your email.", code)


@router.post("/refresh", response_model=TokenResponse)
def refresh_tokens(body: RefreshRequest, db: Session = Depends(get_db)):
    user_id = auth_utils.decode_token(body.refresh_token, "refresh")
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=401, detail="User not found.")
    return TokenResponse(
        access_token=auth_utils.create_access_token(user_id),
        refresh_token=auth_utils.create_refresh_token(user_id),
    )


@router.get("/me", response_model=UserOut)
def get_me(current_user: User = Depends(auth_utils.get_current_user)):
    return current_user


@router.patch("/me", response_model=UserOut)
def update_me(
    body: UserUpdate,
    current_user: User = Depends(auth_utils.get_current_user),
    db: Session = Depends(get_db),
):
    if body.company_name is not None:
        current_user.company_name = body.company_name
    if body.employee_count is not None:
        current_user.employee_count = body.employee_count
    db.commit()
    db.refresh(current_user)
    return current_user
