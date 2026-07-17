export type JobState =
  | "queued"
  | "extracting_metadata"
  | "downloading"
  | "processing"
  | "embedding_metadata"
  | "completed"
  | "failed"
  | "cancelled";

export interface Job {
  id: string;
  url: string;
  video_id: string;
  state: JobState;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  title: string | null;
  channel: string | null;
  thumbnail_url: string | null;
  progress: number | null;
  downloaded_bytes: number | null;
  total_bytes: number | null;
  speed_bytes_per_second: number | null;
  eta_seconds: number | null;
  output_file: string | null;
  file_size: number | null;
  error_code: string | null;
  error_message: string | null;
  warning_message: string | null;
}

export interface Status {
  state: string;
  progress: number;
  queue_length: number;
  current: Job | null;
}

export interface HistoryPage {
  items: Job[];
  page: number;
  page_size: number;
  total: number;
}

export interface Info {
  version: string;
  yt_dlp_version: string;
  ffmpeg_version: string;
  architecture: string;
  output_directory: string;
  database: string;
  queue_limit: number;
}
