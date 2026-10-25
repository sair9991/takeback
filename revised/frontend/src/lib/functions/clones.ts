import type { Clone } from '../types/clone';

const API_BASE = 'http://localhost:8000';

export const clonesList: Clone[] = [
  {
    id: 'saaketh-kesireddy',
    name: 'Saaketh Kesireddy',
    chessUsername: 'stuffyness',
    lichessUsername: 'saakethk',
    playedCount: '100+',
    blitzRating: 1600,
    cloneRating: 1400,
    initials: 'SK',
    bio: 'Aggressive tactical clone with tactical alertness and Sicilian defense.',
    styleDescription: 'Sharp tactical attacker who favors open center games, rapid pawn advances, and dynamic counter-attacks.'
  },
  {
    id: 'magnus-carlsen',
    name: 'Magnus Carlsen',
    chessUsername: 'magnuscarlsen',
    lichessUsername: 'drnykterstein',
    playedCount: '500+',
    blitzRating: 2850,
    cloneRating: 2820,
    initials: 'MC',
    bio: 'World Champion endgame master with deep strategic squeeze.',
    styleDescription: 'Relentless strategic grinder who excels in grinding out tiny endgame edges and applying positional pressure.'
  },
  {
    id: 'hikaru-nakamura',
    name: 'Hikaru Nakamura',
    chessUsername: 'hikaru',
    lichessUsername: 'tsm_hikaru',
    playedCount: '350+',
    blitzRating: 2800,
    cloneRating: 2790,
    initials: 'HN',
    bio: 'Speed demon with ruthless resourcefulness and sharp tactical strikes.',
    styleDescription: 'Hyper-aggressive blitz specialist who thrives in chaotic, rapid positions with tactical alertness and tricky counter-play.'
  },
  {
    id: 'daniel-naroditsky',
    name: 'Daniel Naroditsky',
    chessUsername: 'danielnaroditsky',
    lichessUsername: 'danya',
    playedCount: '220+',
    blitzRating: 2650,
    cloneRating: 2610,
    initials: 'DN',
    bio: 'Dynamic positional master with instructive opening knowledge.',
    styleDescription: 'Textbook tactical master with deep theoretical preparation and principled attacking plans against king safety.'
  },
  {
    id: 'fabiano-caruana',
    name: 'Fabiano Caruana',
    chessUsername: 'fabianocaruana',
    lichessUsername: 'caruanachess',
    playedCount: '180+',
    blitzRating: 2780,
    cloneRating: 2750,
    initials: 'FC',
    bio: 'Deep opening preparation and calculating machine.',
    styleDescription: 'Concrete calculating powerhouse who plays concrete, mathematically precise candidate moves.'
  },
  {
    id: 'levy-rozman',
    name: 'GothamChess (Levy Rozman)',
    chessUsername: 'gothamchess',
    lichessUsername: 'gothamchess',
    playedCount: '310+',
    blitzRating: 2350,
    cloneRating: 2300,
    initials: 'GC',
    bio: 'Aggressive opening gambits, Vienna game specialist, and tactical attacking style.',
    styleDescription: 'Aggressive gambit aficionado who hunts early initiative, dynamic open files, and kingside mating nets.'
  }
];

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
          // Find matching preset clone or create dynamic representation
          const preset = clonesList.find((c) => c.chessUsername.toLowerCase() === playerId.toLowerCase() || c.id === playerId);
          const name = preset ? preset.name : (item.model_name && item.model_name !== 'clone' ? item.model_name : playerId.charAt(0).toUpperCase() + playerId.slice(1));
          const parts = name.split(' ');
          const initials = preset?.initials || (parts.length >= 2 ? (parts[0][0] + parts[1][0]).toUpperCase() : name.slice(0, 2).toUpperCase());

          return {
            id: playerId,
            name: name,
            chessUsername: item.player_id || playerId,
            lichessUsername: preset?.lichessUsername || playerId,
            playedCount: `${item.access_count ?? preset?.playedCount ?? 0}+`,
            blitzRating: preset?.blitzRating || 1800,
            cloneRating: preset?.cloneRating || (item.val_accuracy ? Math.round(item.val_accuracy * 3000) : 1800),
            initials: initials,
            bio: preset?.bio || `Neural network clone of ${name}.`,
            styleDescription: item.style_description || preset?.styleDescription || 'Adaptive neural chess clone.',
            similarityScore: typeof item.similarity_score === 'number' ? item.similarity_score : undefined,
          };
        });
      }
    }
  } catch (err) {
    console.warn('Backend clone fetch failed, using local presets:', err);
  }

  // Fallback to local filtering
  return getClones(query);
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
  const preset = clonesList.find((c) => c.chessUsername.toLowerCase() === playerId.toLowerCase());
  return preset?.styleDescription || 'Dynamic neural chess clone playing with personalized opening preparation and tactical timing.';
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
