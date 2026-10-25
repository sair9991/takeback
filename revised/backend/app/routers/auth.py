import logging
from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.responses import RedirectResponse
from app.config import settings
from app.db.repositories import user_repo
from app.dependencies import get_current_user
from app.schemas.auth import (
    AuthSuccessResponse,
    LoginRequest,
    RegisterRequest,
    UpdateProfileRequest,
    UserResponse,
)
from app.services import auth_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["Authentication"])


def set_auth_cookie(response: Response, token: str) -> None:
    """Set hardened HTTP-only JWT access token cookie."""
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        max_age=settings.JWT_EXPIRE_DAYS * 86400,
        path="/",
    )


def clear_auth_cookie(response: Response) -> None:
    """Delete access token cookie on logout."""
    response.delete_cookie(
        key="access_token",
        httponly=True,
        secure=settings.COOKIE_SECURE,
        samesite="lax",
        path="/",
    )


@router.post("/register", response_model=AuthSuccessResponse)
def register(payload: RegisterRequest, response: Response):
    """Register a new account with email and password."""
    existing = user_repo.get_user_by_email(payload.email)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists",
        )

    password_hash = auth_service.hash_password(payload.password)
    user = user_repo.create_user_with_password(
        email=payload.email,
        password_hash=password_hash,
        chess_com_username=payload.chess_com_username,
    )

    token = auth_service.create_access_token(user["user_id"])
    set_auth_cookie(response, token)
    return AuthSuccessResponse(user=UserResponse(**user))


@router.post("/login", response_model=AuthSuccessResponse)
def login(payload: LoginRequest, response: Response):
    """Authenticate with email and password, setting an HTTP-only session cookie."""
    user = user_repo.get_user_by_email(payload.email)
    if not user or not user.get("password_hash"):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    valid = auth_service.verify_password(payload.password, user["password_hash"])
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = auth_service.create_access_token(user["user_id"])
    set_auth_cookie(response, token)
    return AuthSuccessResponse(user=UserResponse(**user))


@router.post("/logout")
def logout(response: Response):
    """Clear session cookie to log out the user."""
    clear_auth_cookie(response)
    return {"status": "logged_out"}


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(user: dict = Depends(get_current_user)):
    """Retrieve profile of the currently logged-in user."""
    return UserResponse(**user)


@router.patch("/profile", response_model=UserResponse)
def update_profile(payload: UpdateProfileRequest, user: dict = Depends(get_current_user)):
    """Update chess handle (Chess.com or Lichess username) for the authenticated user."""
    updated = user_repo.update_user_profile(
        user_id=user["user_id"],
        chess_com_username=payload.chess_com_username,
        lichess_username=payload.lichess_username,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="User not found")
    return UserResponse(**updated)


@router.get("/google/login")
def google_login_redirect():
    """Redirect client browser to Google OAuth consent screen."""
    if not settings.GOOGLE_CLIENT_ID:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Google OAuth is not configured. Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET.",
        )
    auth_url = auth_service.get_google_auth_url()
    return RedirectResponse(url=auth_url)


@router.get("/google/callback")
async def google_callback(code: str):
    """Handle authorization code callback from Google, issue session, and redirect to frontend."""
    try:
        profile = await auth_service.exchange_google_code_for_user(code)
    except Exception as e:
        logger.error("google auth exchange failed: %s", e)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to authenticate with Google",
        )

    google_id = profile.get("sub")
    email = profile.get("email")
    if not google_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google profile missing required email identifier",
        )

    user = user_repo.get_or_create_google_user(google_id, email)
    token = auth_service.create_access_token(user["user_id"])

    redirect_url = f"{settings.FRONTEND_URL.rstrip('/')}/app"
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    set_auth_cookie(response, token)
    return response
