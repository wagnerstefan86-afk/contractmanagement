"""
Authentication utilities — password hashing and JWT handling.

Password hashing
----------------
Uses bcrypt directly (bcrypt ≥ 4.x) to avoid the passlib/bcrypt version
mismatch present on this system.  The API mirrors passlib's CryptContext:
  hash_password(plain)  → str
  verify_password(plain, hashed) → bool

JWT
---
  create_access_token(payload) → str
  decode_token(token)          → dict   (raises jose.JWTError on failure)

Token payload structure
-----------------------
  {
    "sub":  "user@example.com",   # email (subject)
    "uid":  1,                    # User.id
    "cid":  1,                    # User.customer_id (tenant)
    "role": "ADMIN",              # UserRole value
    "exp":  <unix timestamp>
  }
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import JWT_ALGORITHM, JWT_EXPIRY_HOURS, JWT_SECRET

# ── Password hashing ──────────────────────────────────────────────────────────

# bcrypt silently truncates passwords > 72 bytes.  Pre-hashing with SHA-256
# is a common mitigation, but it introduces other risks (no null byte leakage
# at least).  For this platform, passwords > 72 bytes are rejected at the
# schema level (max 128 chars, all ASCII).

def hash_password(plain: str) -> str:
    """Return a bcrypt hash of *plain*."""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """Return True iff *plain* matches *hashed* (constant-time comparison)."""
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False


# ── JWT helpers ───────────────────────────────────────────────────────────────

def create_access_token(
    *,
    user_id:     int,
    email:       str,
    customer_id: int,
    role:        str,
) -> str:
    """
    Encode a signed JWT access token.

    The ``exp`` claim is set to ``now + JWT_EXPIRY_HOURS``.
    """
    payload = {
        "sub":  email,
        "uid":  user_id,
        "cid":  customer_id,
        "role": role,
        "exp":  datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRY_HOURS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Decode and verify a JWT.

    Raises
    ------
    jose.JWTError
        When the token is invalid, tampered with, or expired.
    """
    return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])


# Re-export so callers can catch the right exception type without importing jose
TokenError = JWTError
