export interface Game {
  id: string;
  opponent: string;
  date: string;
  platform: string;
  initials?: string;
  thumbnailUrl?: string;
  isTraining?: boolean;
  trainingStatus?: string;
  trainingProgress?: number;
  jobId?: string;
  player_id?: string;
  player_elo?: number;
  opponent_elo?: number;
  player_color?: string;
  result?: string;
  time_control?: string;
  narrative?: string;
  tags?: string[];
  similarity_score?: number;
}
