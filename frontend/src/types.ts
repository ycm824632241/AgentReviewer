export type ProgressEvent = {
  node: string;
  label?: string;
  status: string;
};

export type ReviewerConfig = {
  role?: string;
  name?: string;
  target?: string;
  [key: string]: unknown;
};

export type DecisionTrace = {
  original_decision?: string;
  final_decision?: string;
  decision_rationale?: string;
  decision_summary?: string;
  reviewer_recommendations?: Record<string, string>;
  reviewer_weighted_scores?: Record<string, number>;
  da_critical_count?: number;
  applied_rules?: string[];
};

export type RebuttalReviewer = ReviewerConfig & {
  target: string;
};

export type ReviewState = {
  paper_title?: string;
  round_number?: number;
  reviewer_configs?: ReviewerConfig[];
  editorial_decision?: string;
  eic_report?: unknown;
  methodology_report?: unknown;
  domain_report?: unknown;
  perspective_report?: unknown;
  devils_advocate_report?: unknown;
  consensus_analysis?: unknown;
  dimension_scores?: Record<string, number>;
  decision_trace?: DecisionTrace;
  revision_roadmap?: unknown;
  [key: string]: unknown;
};

export type RagDiagnostics = {
  enabled?: boolean;
  reason?: string;
  paper_chars?: number;
  paper_bytes?: number;
  chunk_count?: number;
  chunk_size?: number;
  chunk_overlap?: number;
  chunk_max_bytes?: number;
  max_chunk_bytes?: number;
  embedding_batches?: number;
  chunk_embedding_status?: string;
  query_embedding_failures?: number;
  fallback_used?: boolean;
  cache_hit?: boolean;
  last_error?: string | null;
};

export type ReviewResultResponse = {
  thread_id: string;
  state: ReviewState | null;
  progress: {
    done?: string[];
    finished?: boolean;
    error?: string | null;
    [key: string]: unknown;
  };
  locked: boolean;
  can_resume: boolean;
  job_status?: string | null;
  rag_diagnostics?: RagDiagnostics | null;
};

export type RebuttalInfoResponse = {
  thread_id: string;
  reviewers: RebuttalReviewer[];
  round_number: number;
  locked: boolean;
};

export type HistoryItem = {
  thread_id: string;
  title?: string;
  status?: string;
  can_resume?: boolean;
};

export type HistoryResponse = {
  threads: HistoryItem[];
};

export type ModelSettings = {
  base_url: string;
  api_key: string;
  api_key_set: boolean;
  model: string;
};

export type SettingsPayload = {
  llm: ModelSettings;
  embedding: ModelSettings;
};

export type SettingsUpdate = {
  llm: {
    base_url: string;
    api_key: string;
    model: string;
  };
  embedding: {
    base_url: string;
    api_key: string;
    model: string;
  };
};
