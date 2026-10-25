import type { Game } from './game';

export interface CommentaryMoment {
  phase: string;
  headline: string;
  text: string;
  isPivotal?: boolean;
  pivotalLabel?: string;
  pivotalId?: string;
}

export interface GameAnalysisData {
  game: Game;
  moves: string[];
  evaluationOdds: number[];
  getCommentary: (ply: number) => CommentaryMoment;
}
