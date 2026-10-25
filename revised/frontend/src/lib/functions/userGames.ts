import type { Game } from '../types/game';
import { getMe } from './auth';
export type { Game };

const API_BASE = 'http://localhost:8000';

/**
 * Returns initial empty games list (no dummy data).
 */
export function getUserGames(): Game[] {
  return [];
}

/**
 * Fetches real chess games played by the user from the backend.
 * Never falls back to mock or dummy data.
 */
export async function fetchUserGames(username?: string, forceSync: boolean = false): Promise<Game[]> {
  try {
    let handle = username?.trim();
    if (!handle) {
      const me = await getMe();
      handle = me?.chess_com_username || me?.user_id;
    }
    if (!handle) {
      return [];
    }

    const url = `${API_BASE}/api/users/${encodeURIComponent(handle)}/games?limit=30${forceSync ? '&sync=true' : ''}`;
    const res = await fetch(url, {
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) {
        return data;
      }
    }
  } catch (err) {
    console.warn('Backend not reachable for user games:', err);
  }
  return [];
}

export interface AnalyzeResponse {
  cached: boolean;
  status: 'ready' | 'queued';
  opponent: string;
  game_id?: string;
  job_id?: string;
  stream_url?: string;
  message?: string;
}

/**
 * Checks if the opponent model is cached and starts sequential training if not.
 */
export async function requestGameAnalysis(
  username: string = 'stuffyness',
  gameId: string,
  opponent?: string
): Promise<AnalyzeResponse> {
  const url = opponent
    ? `${API_BASE}/api/users/${username}/analyze/${gameId}?opponent=${encodeURIComponent(opponent)}`
    : `${API_BASE}/api/users/${username}/analyze/${gameId}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
  });
  if (!res.ok) {
    throw new Error(`Failed to request analysis: ${res.statusText}`);
  }
  return res.json();
}
