"""
User management router — Super Admin only
-----------------------------------------
GET    /users/          list all users
POST   /users/          create a new user
GET    /users/{id}      get single user
PATCH  /users/{id}      update role / active status
DELETE /users/{id}      deactivate (soft delete)
"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from core.deps import require_super_admin
from core.security import hash_password
from database.db import SessionLocal
from models.user import User

router = APIRouter(prefix="/users", tags=["User Management"])


# ── Schemas ───────────────────────────────────────────────────────────────────

ALL_PAGES = ["scanner", "crm_excel", "ppt_store", "final_report"]


class CreateUserRequest(BaseModel):
    username:      str
    password:      str
    email:         Optional[str]        = None
    role:          str                  = "admin"   # "admin" | "super_admin"
    allowed_pages: Optional[List[str]]  = None      # None = all; [] = no access


class UpdateUserRequest(BaseModel):
    role:          Optional[str]        = None
    is_active:     Optional[bool]       = None
    email:         Optional[str]        = None
    password:      Optional[str]        = None
    allowed_pages: Optional[List[str]]  = None      # None = keep existing


class UserOut(BaseModel):
    id:            int
    username:      str
    email:         Optional[str]
    role:          str
    allowed_pages: Optional[List[str]]
    is_active:     bool
    created_at:    str
    last_login:    Optional[str]


def _to_out(u: User) -> UserOut:
    return UserOut(
        id=u.id,
        username=u.username,
        email=u.email,
        role=u.role,
        allowed_pages=u.allowed_pages,
        is_active=u.is_active,
        created_at=u.created_at.isoformat() if u.created_at else "",
        last_login=u.last_login.isoformat() if u.last_login else None,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/", summary="List all users (super_admin only)")
def list_users(_: User = Depends(require_super_admin)):
    db = SessionLocal()
    try:
        users = db.query(User).order_by(User.id).all()
        return [_to_out(u) for u in users]
    finally:
        db.close()


@router.post("/", summary="Create a new user (super_admin only)", status_code=201)
def create_user(body: CreateUserRequest, _: User = Depends(require_super_admin)):
    if body.role not in ("admin", "super_admin"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'super_admin'")

    # Validate page keys
    if body.allowed_pages is not None:
        bad = [p for p in body.allowed_pages if p not in ALL_PAGES]
        if bad:
            raise HTTPException(status_code=400, detail=f"Unknown page keys: {bad}. Valid: {ALL_PAGES}")

    db = SessionLocal()
    try:
        existing = db.query(User).filter(User.username == body.username).first()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")

        # super_admin always has None (unrestricted)
        pages = None if body.role == "super_admin" else body.allowed_pages

        user = User(
            username=body.username,
            email=body.email,
            hashed_password=hash_password(body.password),
            role=body.role,
            allowed_pages=pages,
            is_active=True,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        return _to_out(user)
    finally:
        db.close()


@router.get("/{user_id}", summary="Get single user (super_admin only)")
def get_user(user_id: int, _: User = Depends(require_super_admin)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return _to_out(user)
    finally:
        db.close()


@router.patch("/{user_id}", summary="Update user role/status (super_admin only)")
def update_user(user_id: int, body: UpdateUserRequest, _: User = Depends(require_super_admin)):
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")

        if body.role is not None:
            if body.role not in ("admin", "super_admin"):
                raise HTTPException(status_code=400, detail="Invalid role")
            user.role = body.role
            # if upgrading to super_admin, clear page restriction
            if body.role == "super_admin":
                user.allowed_pages = None
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.email is not None:
            user.email = body.email
        if body.password is not None:
            user.hashed_password = hash_password(body.password)
        if body.allowed_pages is not None:
            bad = [p for p in body.allowed_pages if p not in ALL_PAGES]
            if bad:
                raise HTTPException(status_code=400, detail=f"Unknown page keys: {bad}. Valid: {ALL_PAGES}")
            # only apply if user is not super_admin
            if user.role != "super_admin":
                user.allowed_pages = body.allowed_pages

        db.commit()
        db.refresh(user)
        return _to_out(user)
    finally:
        db.close()


@router.delete("/{user_id}", summary="Deactivate a user (super_admin only)")
def deactivate_user(user_id: int, current: User = Depends(require_super_admin)):
    if current.id == user_id:
        raise HTTPException(status_code=400, detail="Cannot deactivate your own account")
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.id == user_id).first()
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        user.is_active = False
        db.commit()
        return {"deactivated": user_id}
    finally:
        db.close()
