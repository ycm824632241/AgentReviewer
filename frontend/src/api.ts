import type { ProgressEvent, ReviewResultResponse } from "./types";

export async function uploadPaper(file: File): Promise<{ thread_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/upload", { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`上传失败：${response.status}`);
  }
  return response.json();
}

export async function fetchResult(threadId: string): Promise<ReviewResultResponse> {
  const response = await fetch(`/api/result/${threadId}`);
  if (!response.ok) {
    throw new Error(`结果读取失败：${response.status}`);
  }
  return response.json();
}

export function openProgressStream(threadId: string, onEvent: (event: ProgressEvent) => void): EventSource {
  const source = new EventSource(`/api/progress/${threadId}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  return source;
}
