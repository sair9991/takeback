import type { Game } from '../types/game';
import { getMe } from './auth';
export type { Game };

const API_BASE = 'http://localhost:8000';

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

/**
 * Synchronous initial fallback for analyzed games.
 */
export function getAnalyzedGames(): Game[] {
  return [];
}

/**
 * Fetches all games that the user has analyzed from the backend.
 */
export async function fetchAnalyzedGames(username?: string): Promise<Game[]> {
  try {
    let handle = username?.trim();
    if (!handle) {
      const me = await getMe();
      handle = me?.chess_com_username || me?.user_id || 'guest';
    }
    const res = await fetch(`${API_BASE}/api/users/${encodeURIComponent(handle)}/analyzed-games`, {
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        return data;
      }
    }
  } catch (err) {
    console.warn('Backend not reachable for analyzed games:', err);
  }
  return [];
}

/**
 * Natural language semantic search through analyzed games using Gemma embeddings.
 */
export async function searchSemanticAnalyzedGames(
  query: string,
  username?: string
): Promise<Game[]> {
  const trimmed = query.trim();
  let handle = username?.trim();
  if (!handle) {
    const me = await getMe();
    handle = me?.chess_com_username || me?.user_id || 'guest';
  }
  if (!trimmed) {
    return fetchAnalyzedGames(handle);
  }
  try {
    const res = await fetch(
      `${API_BASE}/api/users/${encodeURIComponent(handle)}/search-semantic?q=${encodeURIComponent(trimmed)}`,
      { credentials: 'include' }
    );
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        return data;
      }
    }
  } catch (err) {
    console.warn('Semantic game search failed:', err);
  }
  return [];
}
