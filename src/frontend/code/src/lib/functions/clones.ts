import type { Clone } from '../types/clone';

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
    bio: 'Aggressive tactical clone with tactical alertness and Sicilian defense.'
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
    bio: 'World Champion endgame master with deep strategic squeeze.'
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
    bio: 'Speed demon with ruthless resourcefulness and sharp tactical strikes.'
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
    bio: 'Dynamic positional master with instructive opening knowledge.'
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
    bio: 'Deep opening preparation and calculating machine.'
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
    bio: 'Aggressive opening gambits, Vienna game specialist, and tactical attacking style.'
  }
];

export function getClones(query: string = ''): Clone[] {
  const trimmed = query.trim().toLowerCase();
  if (!trimmed) return clonesList;
  return clonesList.filter((clone) => {
    return (
      clone.name.toLowerCase().includes(trimmed) ||
      clone.chessUsername.toLowerCase().includes(trimmed) ||
      clone.lichessUsername.toLowerCase().includes(trimmed)
    );
  });
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

const API_BASE = 'http://localhost:8000';

/**
 * Predicts the next move and updated clock state for an opponent clone.
 */
export async function requestCloneMove(req: PredictStateRequest): Promise<PredictStateResponse> {
  const res = await fetch(`${API_BASE}/api/predict_next_state`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  });
  if (!res.ok) {
    throw new Error(`Failed to predict clone move: ${res.statusText}`);
  }
  return res.json();
}
