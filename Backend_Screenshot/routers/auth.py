"""
Authentication router
---------------------
POST /auth/login   — username + password → JWT token
GET  /auth/me      — returns current user info
POST /auth/logout  — client-side (token is stateless; just a confirmation)
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel

from core.deps import get_current_user
from core.security import create_access_token, verify_password
from database.db import SessionLocal
from models.user import User

router = APIRouter(prefix="/auth", tags=["Auth"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token:  str
    token_type:    str = "bearer"
    role:          str
    username:      str
    allowed_pages: list | None = None   # None = all pages (super_admin)


class UserInfo(BaseModel):
    id:         int
    username:   str
    email:      str | None
    role:       str
    is_active:  bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/login", response_model=TokenResponse)
def login(form: OAuth2PasswordRequestForm = Depends()):
    """
    Accepts form fields: username, password.
    Returns a JWT access token.
    """
    db = SessionLocal()
    try:
        user = db.query(User).filter(
            User.username == form.username,
            User.is_active == True,
        ).first()

        if not user or not verify_password(form.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Update last_login
        user.last_login = datetime.now(timezone.utc)
        db.commit()

        # super_admin always gets None (all pages); others get their allowed list
        pages = None if user.role == "super_admin" else user.allowed_pages

        token = create_access_token(
            user_id=user.id,
            username=user.username,
            role=user.role,
            allowed_pages=pages,
        )
        return TokenResponse(
            access_token=token,
            role=user.role,
            username=user.username,
            allowed_pages=pages,
        )
    finally:
        db.close()


@router.get("/me", response_model=UserInfo)
def me(user: User = Depends(get_current_user)):
    """Return the currently authenticated user's info."""
    return UserInfo(
        id=user.id,
        username=user.username,
        email=user.email,
        role=user.role,
        is_active=user.is_active,
    )


@router.post("/logout")
def logout():
    """
    JWT is stateless — logout is handled client-side by deleting the token.
    This endpoint is a convenience confirmation.
    """
    return {"message": "Logged out successfully"}
