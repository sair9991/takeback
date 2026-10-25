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
}
