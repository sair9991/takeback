export interface Clone {
  id: string;
  name: string;
  chessUsername: string;
  lichessUsername: string;
  playedCount: string;
  blitzRating?: number;
  chessRating?: number;
  cloneRating?: number;
  avatar?: string;
  initials?: string;
  bio?: string;
  styleDescription?: string;
  similarityScore?: number;
}
