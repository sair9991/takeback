from typing import Any, Optional
import uuid
from app.db.connection import query_one, execute


def generate_user_id() -> str:
    """Generate a clean URL-safe unique user identifier."""
    return f"usr_{uuid.uuid4().hex[:12]}"


def get_user_by_id(user_id: str) -> Optional[dict[str, Any]]:
    """Retrieve user record by user_id."""
    sql = "SELECT * FROM users WHERE user_id = %s"
    return query_one(sql, (user_id,))


def get_user_by_email(email: str) -> Optional[dict[str, Any]]:
    """Retrieve user record by email address."""
    sql = "SELECT * FROM users WHERE LOWER(email) = LOWER(%s)"
    return query_one(sql, (email.strip(),))


def get_user_by_google_id(google_id: str) -> Optional[dict[str, Any]]:
    """Retrieve user record by Google OAuth sub identifier."""
    sql = "SELECT * FROM users WHERE google_id = %s"
    return query_one(sql, (google_id,))


def get_user_by_chess_handle(handle: str) -> Optional[dict[str, Any]]:
    """Retrieve user record by Chess.com handle (case-insensitive)."""
    if not handle:
        return None
    sql = "SELECT * FROM users WHERE LOWER(chess_com_username) = LOWER(%s)"
    return query_one(sql, (handle.strip(),))


def ensure_user_exists(user_id: str, chess_com_username: Optional[str] = None) -> str:
    """Ensure a user record exists for foreign key constraints, creating a shadow player record if needed."""
    clean_id = (user_id or "guest").strip()
    existing = get_user_by_id(clean_id)
    if existing:
        return existing["user_id"]

    if chess_com_username:
        by_handle = get_user_by_chess_handle(chess_com_username)
        if by_handle:
            return by_handle["user_id"]

    sql = """
        INSERT INTO users (user_id, chess_com_username)
        VALUES (%s, %s)
        ON CONFLICT (user_id) DO UPDATE SET
            chess_com_username = COALESCE(users.chess_com_username, EXCLUDED.chess_com_username)
    """
    execute(sql, (clean_id, chess_com_username or clean_id))
    return clean_id


def create_user_with_password(
    email: str,
    password_hash: str,
    chess_com_username: Optional[str] = None,
) -> dict[str, Any]:
    """Create a new user record with hashed password."""
    user_id = generate_user_id()
    sql = """
        INSERT INTO users (user_id, email, password_hash, chess_com_username)
        VALUES (%s, %s, %s, %s)
    """
    execute(sql, (user_id, email.strip().lower(), password_hash, chess_com_username))
    user = get_user_by_id(user_id)
    if not user:
        raise RuntimeError("Failed to retrieve user after creation")
    return user


def get_or_create_google_user(google_id: str, email: str) -> dict[str, Any]:
    """Find existing user by google_id or email, or create a new user."""
    user = get_user_by_google_id(google_id)
    if user:
        return user

    # link google oauth id if user originally signed up via email
    user = get_user_by_email(email)
    if user:
        sql = "UPDATE users SET google_id = %s, updated_at = CURRENT_TIMESTAMP WHERE user_id = %s"
        execute(sql, (google_id, user["user_id"]))
        return get_user_by_id(user["user_id"]) or user

    user_id = generate_user_id()
    sql = """
        INSERT INTO users (user_id, email, google_id)
        VALUES (%s, %s, %s)
    """
    execute(sql, (user_id, email.strip().lower(), google_id))
    created = get_user_by_id(user_id)
    if not created:
        raise RuntimeError("Failed to retrieve Google user after creation")
    return created


def update_user_profile(
    user_id: str,
    chess_com_username: Optional[str] = None,
    lichess_username: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Update chess platform usernames for a user."""
    updates: list[str] = []
    params: list[Any] = []
    if chess_com_username is not None:
        updates.append("chess_com_username = %s")
        params.append(chess_com_username.strip())
    if lichess_username is not None:
        updates.append("lichess_username = %s")
        params.append(lichess_username.strip())

    if not updates:
        return get_user_by_id(user_id)

    updates.append("updated_at = CURRENT_TIMESTAMP")
    params.append(user_id)
    sql = f"UPDATE users SET {', '.join(updates)} WHERE user_id = %s"
    execute(sql, tuple(params))
    return get_user_by_id(user_id)
