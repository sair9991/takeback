const API_BASE = 'http://localhost:8000';

export interface User {
  user_id: string;
  email: string;
  chess_com_username?: string;
  lichess_username?: string;
}

export interface AuthResponse {
  user: User;
}

/**
 * Log in with email and password, receiving an HTTP-only session cookie.
 */
export async function login(email: string, password: string): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email, password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to log in');
  }

  const data: AuthResponse = await res.json();
  return data.user;
}

/**
 * Register a new account with email, password, and optional chess.com handle.
 */
export async function register(email: string, password: string, chessComUsername?: string): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({
      email,
      password,
      chess_com_username: chessComUsername || null,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Registration failed');
  }

  const data: AuthResponse = await res.json();
  return data.user;
}

/**
 * Log out and clear HTTP-only session cookie.
 */
export async function logout(): Promise<void> {
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    credentials: 'include',
  }).catch(() => {});
}

/**
 * Update the user profile (e.g., connect Chess.com username).
 */
export async function updateProfile(payload: {
  chess_com_username?: string;
  lichess_username?: string;
}): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/profile`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(errorData.detail || 'Failed to update profile');
  }

  return await res.json();
}

/**
 * Check active session and return current user profile.
 */
export async function getMe(): Promise<User | null> {
  try {
    const res = await fetch(`${API_BASE}/api/auth/me`, {
      method: 'GET',
      credentials: 'include',
    });
    if (res.ok) {
      return await res.json();
    }
  } catch {
    // unauthenticated or offline
  }
  return null;
}

/**
 * Redirect browser to Google OAuth consent screen.
 */
export function startGoogleAuth(): void {
  window.location.href = `${API_BASE}/api/auth/google/login`;
}
