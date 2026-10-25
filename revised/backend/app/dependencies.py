from typing import Optional
from fastapi import Cookie, Header, HTTPException, status
from app.db.repositories import user_repo
from app.services import auth_service


def extract_token(
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> Optional[str]:
    """Extract JWT token from cookie or Authorization Bearer header."""
    if access_token:
        return access_token
    if authorization and authorization.startswith("Bearer "):
        return authorization.split(" ", 1)[1].strip()
    return None


def get_current_user(
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> dict:
    """Validate JWT token and return active user record or raise 401."""
    token = extract_token(access_token, authorization)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )

    user_id = auth_service.decode_access_token(token)
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired or invalid token",
        )

    user = user_repo.get_user_by_id(user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    return user


def get_optional_current_user(
    access_token: Optional[str] = Cookie(None),
    authorization: Optional[str] = Header(None),
) -> Optional[dict]:
    """Return user record if authenticated, otherwise return None."""
    token = extract_token(access_token, authorization)
    if not token:
        return None

    user_id = auth_service.decode_access_token(token)
    if not user_id:
        return None

    return user_repo.get_user_by_id(user_id)
