"""
FastAPI dependency functions.

Dependency tree
---------------
get_current_user          ← validates Bearer JWT, loads User from DB
  └─ require_roles(...)   ← factory that wraps get_current_user with a role gate
       ├─ require_admin          ADMIN only
       ├─ require_analyst_above  ADMIN | ANALYST
       └─ require_any_role       ADMIN | ANALYST | VIEWER (any authenticated user)

get_tenant_contract       ← get_current_user + tenant-scoped Contract lookup
                            returns 404 for cross-tenant access (no info leak)

Tenant isolation guarantee
--------------------------
Every function that touches a Contract or Analysis record goes through
get_tenant_contract (or an equivalent inline filter on customer_id).
Users outside a tenant always receive 404, never 403, so resource existence
is not leaked.
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from .auth import TokenError, decode_token
from .database import get_db
from .models import Contract, User, UserRole

# HTTPBearer auto-returns 403 when the Authorization header is absent.
# We set auto_error=False and handle the missing token ourselves so we can
# return the correct 401 (unauthenticated) rather than 403 (unauthorized).
_bearer = HTTPBearer(auto_error=False)


# ── Core identity dependency ──────────────────────────────────────────────────

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: Session = Depends(get_db),
) -> User:
    """
    Validate the Bearer JWT and return the authenticated User.

    Raises 401 for:
    - missing Authorization header
    - malformed / expired token
    - user not found or deactivated
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Provide a Bearer token.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_token(credentials.credentials)
        user_id: int | None = payload.get("uid")
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or has expired.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload is malformed.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = (
        db.query(User)
        .filter(User.id == user_id, User.is_active.is_(True))
        .first()
    )
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account not found or has been deactivated.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return user


# ── Role-gate dependency factory ──────────────────────────────────────────────

def require_roles(*roles: UserRole):
    """
    Return a dependency that passes when the current user holds one of *roles*.

    Usage::

        @app.post("/something", dependencies=[Depends(require_roles(UserRole.ADMIN))])
        def endpoint(user: User = Depends(get_current_user)):
            ...

    Or inline as the user source::

        def endpoint(user: User = Depends(require_roles(UserRole.ADMIN, UserRole.ANALYST))):
            ...
    """
    allowed = frozenset(roles)

    def _check(user: User = Depends(get_current_user)) -> User:
        if UserRole(user.role) not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    f"This action requires one of the following roles: "
                    f"{', '.join(r.value for r in allowed)}. "
                    f"Your role is {user.role}."
                ),
            )
        return user

    return _check


# ── Pre-built role dependencies ───────────────────────────────────────────────

def require_admin(user: User = Depends(get_current_user)) -> User:
    """Require ADMIN role; raises 403 otherwise."""
    if UserRole(user.role) is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required.",
        )
    return user


def require_analyst_above(user: User = Depends(get_current_user)) -> User:
    """Require ADMIN or ANALYST role; raises 403 otherwise."""
    if UserRole(user.role) not in (UserRole.ADMIN, UserRole.ANALYST):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Analyst or Admin role required.",
        )
    return user


# `require_any_role` is just get_current_user — any authenticated user passes.
require_any_role = get_current_user


# ── Tenant-scoped resource helpers ────────────────────────────────────────────

def get_tenant_contract(
    contract_id: str,
    db:   Session = Depends(get_db),
    user: User    = Depends(get_current_user),
) -> Contract:
    """
    Look up a contract by ID, enforcing tenant isolation.

    Returns the Contract if it belongs to the current user's customer.
    Returns **404** (not 403) when the contract does not exist *or* belongs
    to a different tenant — deliberately preventing resource enumeration.
    """
    contract = (
        db.query(Contract)
        .filter(
            Contract.contract_id == contract_id,
            Contract.customer_id == user.customer_id,
        )
        .first()
    )
    if contract is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Contract '{contract_id}' not found.",
        )
    return contract
