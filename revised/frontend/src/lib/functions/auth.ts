const API_BASE = 'http://localhost:8000';

export interface User {
  user_id: string;
  email: string;
  chess_com_username?: string;
  lichess_username?: string;
}

export interface AuthResponse {
  user: User;
  token?: string;
}

export function getAuthHeaders(extraHeaders: Record<string, string> = {}): Record<string, string> {
  const headers: Record<string, string> = { ...extraHeaders };
  try {
    const token = localStorage.getItem('access_token');
    if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  } catch {}
  return headers;
}

export function formatErrorMessage(errorData: any, fallback: string): string {
  if (!errorData || !errorData.detail) return fallback;
  if (typeof errorData.detail === 'string') return errorData.detail;
  if (Array.isArray(errorData.detail)) {
    return errorData.detail
      .map((e: any) => {
        const field = Array.isArray(e.loc) ? e.loc[e.loc.length - 1] : '';
        const msg = e.msg || e.detail || JSON.stringify(e);
        return field ? `${field}: ${msg}` : msg;
      })
      .join('; ');
  }
  return typeof errorData.detail === 'object' ? JSON.stringify(errorData.detail) : String(errorData.detail);
}

/**
 * Log in with email and password, receiving an HTTP-only session cookie and JWT token.
 */
export async function login(email: string, password: string): Promise<User> {
  const res = await fetch(`${API_BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email: email.trim(), password }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(formatErrorMessage(errorData, 'Failed to log in'));
  }

  const data: AuthResponse = await res.json();
  if (data.token) {
    try {
      localStorage.setItem('access_token', data.token);
    } catch {}
  }
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
      email: email.trim(),
      password,
      chess_com_username: chessComUsername || null,
    }),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(formatErrorMessage(errorData, 'Registration failed'));
  }

  const data: AuthResponse = await res.json();
  if (data.token) {
    try {
      localStorage.setItem('access_token', data.token);
    } catch {}
  }
  return data.user;
}

/**
 * Log out and clear HTTP-only session cookie and local token.
 */
export async function logout(): Promise<void> {
  try {
    localStorage.removeItem('access_token');
  } catch {}
  await fetch(`${API_BASE}/api/auth/logout`, {
    method: 'POST',
    headers: getAuthHeaders(),
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
    headers: getAuthHeaders({ 'Content-Type': 'application/json' }),
    credentials: 'include',
    body: JSON.stringify(payload),
  });

  if (!res.ok) {
    const errorData = await res.json().catch(() => ({}));
    throw new Error(formatErrorMessage(errorData, 'Failed to update profile'));
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
      headers: getAuthHeaders(),
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
