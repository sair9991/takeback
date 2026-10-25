export interface Game {
  id: string;
  opponent: string;
  date: string;
  platform: string;
  initials?: string;
  thumbnailUrl?: string;
}

export function getInitials(name: string): string {
  const parts = name.trim().split(/\s+/);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return name.slice(0, 2).toUpperCase();
}

export function getDummyGames(): Game[] {
  return [
    {
      id: '1',
      opponent: 'Opponent Name',
      date: 'January 1st, 2026',
      platform: 'Chess.com',
      initials: 'OP'
    }
  ];
}

const mockOpponents = [
  'Magnus Carlsen',
  'Hikaru Nakamura',
  'Fabiano Caruana',
  'Levon Aronian',
  'Ian Nepomniachtchi'
];

export function createDummyGame(index: number = 2): Game {
  const opponent = mockOpponents[(index - 2) % mockOpponents.length] || `Opponent ${index}`;
  const now = new Date();
  const dateStr = now.toLocaleDateString('en-US', {
    month: 'long',
    day: 'numeric',
    year: 'numeric'
  });

  return {
    id: String(Date.now()),
    opponent,
    date: dateStr,
    platform: index % 2 === 0 ? 'Chess.com' : 'Lichess',
    initials: getInitials(opponent)
  };
}
