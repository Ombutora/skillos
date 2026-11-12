import re

import jwt
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import LoginIn, Page, RefreshIn, RegisterIn, TokenOut, UserCreateIn, UserOut
from app.core.audit import audit
from app.core.db import get_db
from app.core.deps import current_user, require, same_org
from app.core.ratelimit import limiter
from app.core.security import create_access_token, create_refresh_token, decode_token, hash_password, verify_password
from app.models import Organization, Role, User

router = APIRouter(tags=["auth"])


def _tokens(u: User) -> TokenOut:
    return TokenOut(access_token=create_access_token(u.id, u.org_id, u.role.value), refresh_token=create_refresh_token(u.id))


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:90] or "org"


@router.post("/auth/register", response_model=TokenOut, status_code=201, dependencies=[Depends(limiter("register", 10))])
def register(body: RegisterIn, db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "email already registered")
    slug, n = _slug(body.organization_name), 1
    base = slug
    while db.scalar(select(Organization).where(Organization.slug == slug)):
        n += 1
        slug = f"{base}-{n}"
    org = Organization(name=body.organization_name.strip(), slug=slug)
    db.add(org)
    db.flush()
    u = User(org_id=org.id, email=body.email.lower(), full_name=body.full_name.strip(),
             password_hash=hash_password(body.password), role=Role.ADMIN)
    db.add(u)
    db.flush()
    audit(db, u, "org.created", "organization", org.id)
    db.commit()
    return _tokens(u)


@router.post("/auth/login", response_model=TokenOut, dependencies=[Depends(limiter("login", 20))])
def login(body: LoginIn, db: Session = Depends(get_db)):
    u = db.scalar(select(User).where(User.email == body.email.lower()))
    if u is None or not verify_password(body.password, u.password_hash) or not u.is_active:
        raise HTTPException(401, "invalid email or password")
    audit(db, u, "auth.login")
    db.commit()
    return _tokens(u)


@router.post("/auth/refresh", response_model=TokenOut, dependencies=[Depends(limiter("refresh", 60))])
def refresh(body: RefreshIn, db: Session = Depends(get_db)):
    try:
        payload = decode_token(body.refresh_token, "refresh")
    except jwt.PyJWTError:
        raise HTTPException(401, "invalid refresh token") from None
    u = db.get(User, payload["sub"])
    if u is None or not u.is_active:
        raise HTTPException(401, "user not found")
    return _tokens(u)


@router.get("/auth/me", response_model=UserOut)
def me(user: User = Depends(current_user)):
    return user


@router.get("/users", response_model=Page[UserOut])
def list_users(role: str | None = None, limit: int = 50, offset: int = 0,
               user: User = Depends(require(Role.ADMIN, Role.EXPERT)), db: Session = Depends(get_db)):
    q = select(User).where(User.org_id == user.org_id)
    if role:
        q = q.where(User.role == Role(role))
    rows = db.scalars(q.order_by(User.created_at)).all()
    return Page(items=rows[offset:offset + limit], total=len(rows), limit=limit, offset=offset)


@router.post("/users", response_model=UserOut, status_code=201)
def create_user(body: UserCreateIn, admin: User = Depends(require(Role.ADMIN)), db: Session = Depends(get_db)):
    if db.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "email already registered")
    u = User(org_id=admin.org_id, email=body.email.lower(), full_name=body.full_name,
             password_hash=hash_password(body.password), role=Role(body.role))
    db.add(u)
    db.flush()
    audit(db, admin, "user.created", "user", u.id, role=body.role)
    db.commit()
    return u


@router.delete("/users/{user_id}", status_code=204)
def deactivate_user(user_id: str, admin: User = Depends(require(Role.ADMIN)), db: Session = Depends(get_db)):
    u = same_org(db.get(User, user_id), admin)
    if u.id == admin.id:
        raise HTTPException(400, "cannot deactivate yourself")
    u.is_active = False
    audit(db, admin, "user.deactivated", "user", u.id)
    db.commit()
