import type { Game } from '../types/game';
export type { Game };

const API_BASE = 'http://localhost:8000';

export const FALLBACK_GAMES: Game[] = [
  { id: 'stuffyness_2025.04.20_0', opponent: 'Zzlatko', date: '2025.04.20', platform: 'Chess.com', initials: 'ZZ', player_color: 'black', player_elo: 1813, opponent_elo: 1850, time_control: '600' },
  { id: 'stuffyness_2025.04.20_1', opponent: 'Lolitoarg', date: '2025.04.20', platform: 'Chess.com', initials: 'LO', player_color: 'white', player_elo: 1821, opponent_elo: 1818, time_control: '600' },
  { id: 'stuffyness_2025.04.20_2', opponent: 'Parvaz55', date: '2025.04.20', platform: 'Chess.com', initials: 'PA', player_color: 'black', player_elo: 1813, opponent_elo: 1844, time_control: '600' },
  { id: 'stuffyness_2025.04.21_3', opponent: 'logan40', date: '2025.04.21', platform: 'Chess.com', initials: 'LO', player_color: 'white', player_elo: 1821, opponent_elo: 1816, time_control: '600' },
  { id: 'stuffyness_2025.04.21_4', opponent: 'neb84', date: '2025.04.21', platform: 'Chess.com', initials: 'NE', player_color: 'black', player_elo: 1814, opponent_elo: 1825, time_control: '600' },
];

/**
 * Returns synchronous fallback games list.
 */
export function getUserGames(): Game[] {
  return FALLBACK_GAMES;
}

/**
 * Fetches all chess games played by the user across connected platforms from backend.
 */
export async function fetchUserGames(username: string = 'stuffyness'): Promise<Game[]> {
  try {
    const res = await fetch(`${API_BASE}/api/users/${username}/games?limit=30`, {
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        return data;
      }
    }
  } catch (err) {
    console.warn('Backend not reachable, using fallback games:', err);
  }
  return FALLBACK_GAMES;
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
