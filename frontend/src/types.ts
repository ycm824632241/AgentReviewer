export type ProgressEvent = {
  node: string;
  label?: string;
  status: string;
};

export type ReviewerConfig = {
  role?: string;
  name?: string;
  [key: string]: unknown;
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
  progress: Record<string, unknown>;
  locked: boolean;
};

export type RebuttalInfoResponse = {
  thread_id: string;
  reviewers: ReviewerConfig[];
  round_number: number;
  locked: boolean;
};

export type HistoryResponse = {
  threads: Array<{ thread_id: string }>;
};
