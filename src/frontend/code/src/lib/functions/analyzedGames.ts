import type { Game } from '../types/game';
export type { Game };

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

/**
 * Returns all games that the user has analyzed in the past.
 * Starts off with 0 default games.
 */
export function getAnalyzedGames(userId: string = 'current_user'): Game[] {
  return [];
}
