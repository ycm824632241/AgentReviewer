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
  revision_roadmap?: unknown;
  [key: string]: unknown;
};

export type ReviewResultResponse = {
  thread_id: string;
  state: ReviewState | null;
  progress: {
    finished?: boolean;
    error?: string | null;
    [key: string]: unknown;
  };
  locked: boolean;
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
