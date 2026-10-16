"""
Security and cryptographic services: password hashing (bcrypt) and JWT signing/verification.
"""
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

import bcrypt
from fastapi import HTTPException, status
from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def hash_password(password: str) -> str:
    """Hash a plaintext password using bcrypt."""
    if not password:
        raise ValueError("Password cannot be empty.")
    # Bcrypt maximum input length is 72 bytes
    pwd_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt(rounds=12)
    return bcrypt.hashpw(pwd_bytes, salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against a stored bcrypt hash."""
    if not plain_password or not hashed_password:
        return False
    try:
        pwd_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pwd_bytes, hash_bytes)
    except Exception:
        return False


def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a signed JWT access token with expiration."""
    to_encode = data.copy()
    now = datetime.now(timezone.utc)
    if expires_delta:
        expire = now + expires_delta
    else:
        expire = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({"iat": now, "exp": expire})
    secret = settings.SECRET_KEY
    if not secret:
        raise ValueError("SECRET_KEY is not configured.")

    return jwt.encode(to_encode, secret, algorithm=settings.JWT_ALGORITHM)


import threading

_revoked_tokens: Dict[str, float] = {}
_revocation_lock = threading.Lock()


def revoke_token(token: str) -> None:
    """Revoke a token immediately by adding it to the revocation store until its expiration."""
    try:
        payload = jwt.decode(
            token,
            settings.SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
            options={"verify_exp": False},
        )
        exp = float(payload.get("exp", datetime.now(timezone.utc).timestamp() + 3600))
    except Exception:
        exp = datetime.now(timezone.utc).timestamp() + 3600

    now = datetime.now(timezone.utc).timestamp()
    with _revocation_lock:
        # Clean expired revoked tokens
        expired_keys = [k for k, v in _revoked_tokens.items() if v < now]
        for k in expired_keys:
            del _revoked_tokens[k]
        _revoked_tokens[token] = exp


def is_token_revoked(token: str) -> bool:
    """Check if token has been revoked."""
    now = datetime.now(timezone.utc).timestamp()
    with _revocation_lock:
        if token in _revoked_tokens:
            if _revoked_tokens[token] >= now:
                return True
            else:
                del _revoked_tokens[token]
    return False


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decode, verify signature, and validate expiration of a JWT access token.
    Raises HTTPException(401) on invalid, expired, or revoked token.
    """
    secret = settings.SECRET_KEY
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server security configuration error.",
        )

    if is_token_revoked(token):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has been revoked.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[settings.JWT_ALGORITHM],
        )
        user_id: Optional[str] = payload.get("sub")
        if user_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials.",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate authentication credentials.",
            headers={"WWW-Authenticate": "Bearer"},
        )
