import type { Game } from '../types/game';
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
export async function fetchAnalyzedGames(username: string = 'stuffyness'): Promise<Game[]> {
  try {
    const res = await fetch(`${API_BASE}/api/users/${username}/analyzed-games`, {
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
  username: string = 'stuffyness'
): Promise<Game[]> {
  const trimmed = query.trim();
  if (!trimmed) {
    return fetchAnalyzedGames(username);
  }
  try {
    const res = await fetch(
      `${API_BASE}/api/users/${username}/search-semantic?q=${encodeURIComponent(trimmed)}`,
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
