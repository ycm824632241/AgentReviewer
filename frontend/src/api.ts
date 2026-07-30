import type { HistoryResponse, ProgressEvent, RebuttalInfoResponse, ReviewResultResponse, SettingsPayload, SettingsUpdate } from "./types";

async function readJson<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${action}失败：${response.status} ${detail}`);
  }
  return response.json();
}

export async function uploadPaper(file: File): Promise<{ thread_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return readJson(await fetch("/api/upload", { method: "POST", body: form }), "上传");
}

export async function fetchResult(threadId: string): Promise<ReviewResultResponse> {
  return readJson(await fetch(`/api/result/${threadId}`), "读取结果");
}

export async function fetchRebuttalInfo(threadId: string): Promise<RebuttalInfoResponse> {
  return readJson(await fetch(`/api/rebuttal/${threadId}`), "读取 Rebuttal 信息");
}

export async function resumeReview(threadId: string): Promise<{ status: string; thread_id: string }> {
  return readJson(await fetch(`/api/resume/${threadId}`, { method: "POST" }), "继续审稿");
}

export async function submitRebuttal(threadId: string, target: string, text: string): Promise<{ status: string; round: number; thread_id: string }> {
  const form = new FormData();
  form.append("target", target);
  form.append("text", text);
  return readJson(await fetch(`/api/rebuttal/${threadId}`, { method: "POST", body: form }), "提交 Rebuttal");
}

export async function fetchHistory(): Promise<HistoryResponse> {
  return readJson(await fetch("/api/history"), "读取历史记录");
}

export async function fetchSettings(): Promise<SettingsPayload> {
  return readJson(await fetch("/api/settings"), "读取设置");
}

export async function saveSettings(settings: SettingsUpdate): Promise<SettingsPayload> {
  return readJson(
    await fetch("/api/settings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(settings)
    }),
    "保存设置"
  );
}

export function openProgressStream(threadId: string, onEvent: (event: ProgressEvent) => void): EventSource {
  const source = new EventSource(`/api/progress/${threadId}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  return source;
}
