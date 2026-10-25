import type { Clone } from '../types/clone';

const API_BASE = 'http://localhost:8000';

export const clonesList: Clone[] = [];

export function getClones(query: string = ''): Clone[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return clonesList;
  return clonesList.filter((clone) => {
    return (
      clone.name.toLowerCase().includes(trimmed) ||
      clone.chessUsername.toLowerCase().includes(trimmed) ||
      clone.lichessUsername.toLowerCase().includes(trimmed) ||
      (clone.styleDescription && clone.styleDescription.toLowerCase().includes(trimmed)) ||
      (clone.bio && clone.bio.toLowerCase().includes(trimmed))
    );
  });
}

/**
 * Fetch clones from backend, searching by natural language style or listing all.
 */
export async function fetchClones(query: string = ''): Promise<Clone[]> {
  const trimmed = query.trim();
  try {
    const url = trimmed
      ? `${API_BASE}/api/clones/search?q=${encodeURIComponent(trimmed)}`
      : `${API_BASE}/api/clones`;

    const res = await fetch(url, { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        return data.map((item: any) => {
          const playerId = item.player_id || item.id || 'clone';
          const name =
            item.model_name && item.model_name !== 'clone'
              ? item.model_name
              : playerId.charAt(0).toUpperCase() + playerId.slice(1);
          const parts = name.split(' ');
          const initials =
            parts.length >= 2
              ? (parts[0][0] + parts[1][0]).toUpperCase()
              : name.slice(0, 2).toUpperCase();

          const realRating =
            item.chess_elo ||
            item.blitz_rating ||
            item.chess_rating ||
            (item.opponent_elo ? Number(item.opponent_elo) : undefined);

          return {
            id: playerId,
            name: name,
            chessUsername: item.player_id || playerId,
            lichessUsername: playerId,
            playedCount: `${item.access_count ?? 0}+`,
            blitzRating: realRating,
            chessRating: realRating,
            cloneRating: realRating,
            initials: initials,
            bio: item.bio || `Neural network clone of ${name}.`,
            styleDescription: item.style_description || 'Adaptive neural chess clone.',
            similarityScore: typeof item.similarity_score === 'number' ? item.similarity_score : undefined,
          };
        });
      }
      return [];
    }
  } catch (err) {
    console.warn('Backend clone fetch failed:', err);
  }

  return [];
}

/**
 * Fetch a Gemma-powered playing style description for a specific clone.
 */
export async function fetchCloneStyle(playerId: string): Promise<string> {
  try {
    const res = await fetch(`${API_BASE}/api/clones/${encodeURIComponent(playerId)}/style`, {
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      if (data?.style_description) {
        return data.style_description;
      }
    }
  } catch (err) {
    console.warn('Failed to fetch clone style profile:', err);
  }
  return 'Dynamic neural chess clone playing with personalized opening preparation and tactical timing.';
}

/**
 * Fetch recorded past games between the user and a specific opponent clone.
 */
export async function fetchClonePastGames(playerId: string, userHandle?: string): Promise<any[]> {
  try {
    const url = userHandle
      ? `${API_BASE}/api/clones/${encodeURIComponent(playerId)}/past-games?user=${encodeURIComponent(userHandle)}`
      : `${API_BASE}/api/clones/${encodeURIComponent(playerId)}/past-games`;
    const res = await fetch(url, { credentials: 'include' });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data)) return data;
    }
  } catch (err) {
    console.warn('Failed to fetch past games against clone:', err);
  }
  return [];
}

/**
 * Fetch model metadata, accuracy, and access stats for a specific opponent clone.
 */
export async function fetchCloneStats(playerId: string): Promise<any | null> {
  try {
    const res = await fetch(`${API_BASE}/api/clones/${encodeURIComponent(playerId)}/stats`, {
      credentials: 'include',
    });
    if (res.ok) {
      return await res.json();
    }
  } catch (err) {
    console.warn('Failed to fetch clone model stats:', err);
  }
  return null;
}

export interface PredictStateRequest {
  fen: string;
  opponent_color: 'white' | 'black';
  my_clock: number;
  opponent_clock: number;
  opponent_username?: string;
  opponent_elo?: number;
  my_elo?: number;
}

export interface PredictStateResponse {
  move: string;
  san: string;
  uci: string;
  fen: string;
  think_time: number;
  opponent_clock: number;
  my_clock: number;
  is_check: boolean;
  is_game_over: boolean;
}

/**
 * Predicts the next move and updated clock state for an opponent clone using the Maia-3 + Clone neural net.
 */
export async function requestCloneMove(req: PredictStateRequest): Promise<PredictStateResponse> {
  const res = await fetch(`${API_BASE}/api/predict-next-state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    const errData = await res.json().catch(() => ({}));
    throw new Error(errData.detail || `Failed to predict clone move (${res.status}: ${res.statusText})`);
  }
  return res.json();
}
