import type { Game } from '../types/game';
export type { Game };

/**
 * Returns all chess games played by the user in general across their connected platforms (Chess.com, Lichess).
 * Called when the user clicks 'Import game' in the New Analysis modal to select a game to analyze.
 */
export function getUserGames(username: string = 'stuffyness'): Game[] {
  return [
    {
      id: 'import-1',
      opponent: 'Zzlatko',
      date: 'April 20th, 2025',
      platform: 'Chess.com',
      initials: 'ZZ'
    },
    {
      id: 'import-2',
      opponent: 'Lolitoarg',
      date: 'April 20th, 2025',
      platform: 'Chess.com',
      initials: 'LO'
    },
    {
      id: 'import-3',
      opponent: 'Parvaz55',
      date: 'April 20th, 2025',
      platform: 'Chess.com',
      initials: 'PA'
    },
    {
      id: 'import-4',
      opponent: 'logan40',
      date: 'April 21st, 2025',
      platform: 'Chess.com',
      initials: 'LO'
    },
    {
      id: 'import-5',
      opponent: 'neb84',
      date: 'April 21st, 2025',
      platform: 'Chess.com',
      initials: 'NE'
    },
    {
      id: 'import-6',
      opponent: 'Opponent Name',
      date: 'January 1st, 2026',
      platform: 'Chess.com',
      initials: 'OP'
    }
  ];
}
