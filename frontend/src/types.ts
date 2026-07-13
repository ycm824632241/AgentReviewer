export type ProgressEvent = {
  node: string;
  label?: string;
  status: string;
};

export type ReviewResultResponse = {
  thread_id: string;
  state: Record<string, unknown> | null;
  progress: Record<string, unknown>;
  locked: boolean;
};
