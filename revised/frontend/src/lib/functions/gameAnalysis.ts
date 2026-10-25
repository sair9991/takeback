import type { Game, CommentaryMoment, GameAnalysisData } from '../types';
import { getAnalyzedGames, getInitials } from './analyzedGames';
import { getUserGames } from './userGames';

export type { CommentaryMoment, GameAnalysisData };

/**
 * Complete classic sample game moves for replay and analysis:
 * Paul Morphy's Opera Game (33 plies, finishes with checkmate)
 */
export const samplePgnMoves: string[] = [
  'e4', 'e5',
  'Nf3', 'd6',
  'd4', 'Bg4',
  'dxe5', 'Bxf3',
  'Qxf3', 'dxe5',
  'Bc4', 'Nf6',
  'Qb3', 'Qe7',
  'Nc3', 'c6',
  'Bg5', 'b5',
  'Nxb5', 'cxb5',
  'Bxb5+', 'Nbd7',
  'O-O-O', 'Rd8',
  'Rxd7', 'Rxd7',
  'Rd1', 'Qe6',
  'Bxd7+', 'Nxd7',
  'Qb8+', 'Nxb8',
  'Rd8#'
];

/**
 * Dynamic evaluation odds progression (starts at 50/50, ends at 100/0 checkmate)
 */
export const evaluationOdds: number[] = [
  50, 50,
  52, 51,
  54, 53,
  57, 55,
  60, 58,
  65, 62,
  69, 66,
  73, 70,
  76, 73,
  80, 77,
  84, 82,
  88, 85,
  91, 89,
  94, 92,
  96, 95,
  98, 97,
  100
];

/**
 * Returns the contextual coaching and game commentary for a given ply.
 */
export function getCommentaryForPly(ply: number, game?: Game): CommentaryMoment {
  if (ply < 0) {
    return {
      phase: 'Game Setup',
      headline: `Opera Game: Morphy vs. ${game?.opponent || 'Allies (1858)'}`,
      text: "Paul Morphy takes White against Duke Karl of Brunswick and Count Isouard in Paris. White begins with classical King's Pawn development."
    };
  }
  if (ply <= 1) {
    return {
      phase: 'Opening',
      headline: 'Open Game Initiative',
      text: "Both sides contest the center immediately with 1.e4 e5, fighting for central control and opening avenues for bishops and queens."
    };
  }
  if (ply <= 3) {
    return {
      phase: 'Opening',
      headline: 'Philidor Defense',
      text: "Black adopts the Philidor Defense (2...d6). While solid, it restricts Black's dark-squared bishop and concedes spatial freedom to White."
    };
  }
  if (ply <= 5) {
    return {
      phase: 'Opening',
      headline: 'Center Break & Early Pin',
      text: "Morphy strikes the center with 3.d4. Black attempts to pin the knight with 3...Bg4, but White prepares to seize tempo and open lines."
    };
  }
  if (ply <= 7) {
    return {
      phase: 'Opening',
      headline: 'Conceding the Bishop Pair',
      text: "Black surrenders the light-squared bishop (4...Bxf3 5.Qxf3). White regains the piece with queen centralization and opens diagonal attacking avenues."
    };
  }
  if (ply <= 9) {
    return {
      phase: 'Development',
      headline: 'Rapid White Mobilization',
      text: "With 5...dxe5, the center opens up. Morphy now has open diagonals for both bishops and a centralized queen ready to launch attacking threats."
    };
  }
  if (ply <= 11) {
    return {
      phase: 'Attack',
      headline: 'Pressure on f7',
      text: "Morphy plays 6.Bc4, taking aim at Black's sensitive f7 weak point. Black blocks with 6...Nf6, but White's tactical pressure is mounting."
    };
  }
  if (ply <= 13) {
    return {
      phase: 'Attack',
      headline: 'Dual Threats (f7 & b7)',
      text: "7.Qb3 creates simultaneous mating threats on f7 and material threats on b7. Black defends f7 with 7...Qe7, falling further behind in piece development."
    };
  }
  if (ply <= 15) {
    return {
      phase: 'Development',
      headline: 'Relentless Piece Mobilization',
      text: "Morphy develops 8.Nc3, ignoring the pawn grab on b7 to prioritize total piece mobilization. Black plays 8...c6 to blunt the diagonal."
    };
  }
  if (ply <= 17) {
    return {
      phase: 'Critical Moment',
      headline: 'The Pin & The Counter-Thrust',
      text: "Morphy pins Black's knight with 9.Bg5. Black lashes out with 9...b5? attempting to kick the bishop, but fatally neglects king safety in the center.",
      isPivotal: true,
      pivotalLabel: 'Blunder',
      pivotalId: 'move-9-blunder'
    };
  }
  if (ply <= 19) {
    return {
      phase: 'Positional Sacrifice',
      headline: '10.Nxb5! Stripping the King',
      text: "Brilliant knight sacrifice! Morphy trades a knight for two pawns with 10.Nxb5! cxb5 to blow open files directly toward Black's uncastled monarch.",
      isPivotal: true,
      pivotalLabel: 'Piece Sac',
      pivotalId: 'move-10-sacrifice'
    };
  }
  if (ply <= 21) {
    return {
      phase: 'Tactical Pin',
      headline: 'Paralysis on the d-file',
      text: "11.Bxb5+ delivers check and forces Black into an agonizing pin with 11...Nbd7. Black's pieces are immobilized and tripping over each other."
    };
  }
  if (ply <= 23) {
    return {
      phase: 'Attack',
      headline: 'Queenside Castling with Tempo',
      text: "Morphy castles queenside (0-0-0)! In classical chess, castling activates the rook directly onto the open d-file with crushing pressure against d7."
    };
  }
  if (ply <= 25) {
    return {
      phase: 'Exchange Sacrifice',
      headline: '13.Rxd7! Shattering the Defense',
      text: "Morphy gives up a rook for a knight to eliminate Black's key defender. Black is forced to recapture 13...Rxd7, remaining pinned and helpless.",
      isPivotal: true,
      pivotalLabel: 'Rook Sac',
      pivotalId: 'move-13-exchange'
    };
  }
  if (ply <= 27) {
    return {
      phase: 'Attack',
      headline: 'Complete Piece Harmony',
      text: "14.Rd1 brings White's last remaining piece into the assault. All of Morphy's active pieces are participating while Black's kingside pieces remain asleep."
    };
  }
  if (ply <= 29) {
    return {
      phase: 'Decisive Strike',
      headline: 'Defenders Eliminated',
      text: "15.Bxd7+ simplifies into an irresistible mating net. Black's knight recaptures on d7, leaving Black's king with zero escape squares."
    };
  }
  if (ply <= 31) {
    return {
      phase: 'Queen Sacrifice',
      headline: '16.Qb8+!! The Immortal Deflection',
      text: "A legendary queen sacrifice! Morphy plays 16.Qb8+!, forcing 16...Nxb8 and deflecting Black's knight from covering d8.",
      isPivotal: true,
      pivotalLabel: 'Queen Sac',
      pivotalId: 'move-16-queen-sac'
    };
  }
  return {
    phase: 'Checkmate',
    headline: '17.Rd8# Immortal Checkmate!',
    text: "Checkmate! The d-file rook delivers the fatal blow, protected by the bishop on g5. A masterpiece of development, tempo, and piece coordination.",
    isPivotal: true,
    pivotalLabel: 'Checkmate',
    pivotalId: 'move-17-checkmate'
  };
}

/**
 * Retrieves the full analysis dataset for a given game ID for the /app/analyze/[id] page.
 */
export function getGameAnalysis(gameId?: string): GameAnalysisData {
  const analyzedGames = getAnalyzedGames();
  const userGames = getUserGames();

  // Find game across analyzed or user games, or provide a default fallback
  const found = analyzedGames.find((g) => g.id === gameId) ||
                userGames.find((g) => g.id === gameId);

  const game: Game = found ? { ...found } : {
    id: gameId || '1',
    opponent: 'Opponent Name',
    date: 'January 1st, 2026',
    platform: 'Chess.com'
  };

  if (!game.initials && game.opponent) {
    game.initials = getInitials(game.opponent);
  }

  return {
    game,
    moves: samplePgnMoves,
    evaluationOdds,
    getCommentary: (ply: number) => getCommentaryForPly(ply, game)
  };
}

export interface MoveRecord {
  ply: number;
  side: string;
  move: string;
  time_remaining: number;
  clock_str: string;
}

const API_BASE = 'http://localhost:8000';

/**
 * Fetches full game metadata along with real moves and clocks from the backend.
 */
export async function fetchGameDetail(
  gameId: string
): Promise<{
  game: Game | null;
  moves: string[];
  records: MoveRecord[];
  odds: number[];
  commentary: CommentaryMoment[];
  narrative: string;
  error?: string;
}> {
  try {
    const res = await fetch(`${API_BASE}/api/games/${gameId}`, {
      credentials: 'include',
    });
    if (res.ok) {
      const data = await res.json();
      const { moves, odds, commentary, narrative, error: gemmaError, ...gameData } = data;
      return {
        game: gameData as Game,
        moves: Array.isArray(moves) ? moves.map((m: any) => m.move) : [],
        records: Array.isArray(moves) ? moves : [],
        odds: Array.isArray(odds) ? odds : [],
        commentary: Array.isArray(commentary) ? commentary : [],
        narrative: typeof narrative === 'string' ? narrative : '',
        error: gemmaError || undefined
      };
    } else {
      const err = await res.json().catch(() => ({}));
      return {
        game: null,
        moves: [],
        records: [],
        odds: [],
        commentary: [],
        narrative: '',
        error: err.detail || 'Failed to load game detail'
      };
    }
  } catch (err) {
    console.warn('Backend game detail fetch failed:', err);
    return {
      game: null,
      moves: [],
      records: [],
      odds: [],
      commentary: [],
      narrative: '',
      error: String(err)
    };
  }
}

/**
 * Fetches real moves and clocks for a game from the backend SQLite database.
 */
export async function fetchGameMoves(gameId: string): Promise<{ moves: string[]; records: MoveRecord[] }> {
  try {
    const res = await fetch(`${API_BASE}/api/games/${gameId}/moves`, {
      credentials: 'include',
    });
    if (res.ok) {
      const data: MoveRecord[] = await res.json();
      if (Array.isArray(data) && data.length > 0) {
        return {
          moves: data.map((d) => d.move),
          records: data
        };
      }
    }
  } catch (err) {
    console.warn('Backend moves fetch failed, using fallback:', err);
  }
  return { moves: [], records: [] };
}

/** Alias for getGameAnalysis */
export const getGameAnalysisData = getGameAnalysis;
