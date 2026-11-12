import uuid
from datetime import UTC, datetime, timedelta

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.core.config import get_settings

_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, hashed: str) -> bool:
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def _token(sub: str, kind: str, ttl: timedelta, extra: dict | None = None) -> str:
    s = get_settings()
    now = datetime.now(UTC)
    payload = {"sub": sub, "type": kind, "iat": now, "exp": now + ttl, "jti": uuid.uuid4().hex}
    payload.update(extra or {})
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)


def create_access_token(user_id: str, org_id: str, role: str) -> str:
    s = get_settings()
    return _token(user_id, "access", timedelta(minutes=s.access_token_minutes), {"org": org_id, "role": role})


def create_refresh_token(user_id: str) -> str:
    return _token(user_id, "refresh", timedelta(days=get_settings().refresh_token_days))


def decode_token(token: str, expected_type: str) -> dict:
    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    if payload.get("type") != expected_type:
        raise jwt.InvalidTokenError("wrong token type")
    return payload
