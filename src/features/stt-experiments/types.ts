export type ModelOption = { id: string; label: string; available: boolean; reason: string };
export type ChunkResult = {
  index: number; start_seconds: number; duration_seconds: number; text: string;
  latency_ms: number; skipped: boolean; rms: number;
};
export type ModelResult = {
  model_id: string; label: string; state: string; transcript: string;
  load_ms: number | null; warmup_ms: number | null; error: string | null;
  chunks: ChunkResult[];
  metrics: null | {
    cer: number | null; processing_ms: number; rtf: number; p95_chunk_ms: number;
    skipped_chunks: number; filler_counts: Record<string, number>;
  };
  memory?: { process_tree_peak_rss_mb: number; process_tree_rss_increase_mb: number };
};
export type ExperimentJob = {
  id: string; state: string; cancel_requested: boolean; created_at: string;
  audio_sha256: string; audio_seconds: number; reference: string; chunk_seconds: number;
  warmup: boolean; results: ModelResult[]; models: string[]; error?: string;
  progress: null | { model_id: string; chunk: number; total: number };
  environment: Record<string, unknown>; notes: string[];
};
