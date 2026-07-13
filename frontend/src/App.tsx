import { useEffect, useMemo, useState } from "react";
import { fetchHistory, fetchResult, fetchRebuttalInfo, openProgressStream, submitRebuttal, uploadPaper } from "./api";
import type { ProgressEvent, RebuttalInfoResponse, ReviewResultResponse, ReviewState } from "./types";

const reviewerReports: Array<[keyof ReviewState, string]> = [
  ["eic_report", "Editor-in-Chief"],
  ["methodology_report", "方法论专家"],
  ["domain_report", "领域专家"],
  ["perspective_report", "跨学科视角"],
  ["devils_advocate_report", "Devil's Advocate"]
];

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<ReviewResultResponse | null>(null);
  const [rebuttalInfo, setRebuttalInfo] = useState<RebuttalInfoResponse | null>(null);
  const [history, setHistory] = useState<Array<{ thread_id: string }>>([]);
  const [target, setTarget] = useState("all");
  const [rebuttalText, setRebuttalText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const finished = events.some((event) => event.node === "__all__");
  const state = result?.state;

  const progressLabel = useMemo(() => {
    if (!threadId) return "等待上传";
    if (finished) return "审稿完成";
    return "审稿进行中";
  }, [finished, threadId]);

  async function refreshHistory() {
    const data = await fetchHistory();
    setHistory(data.threads);
  }

  async function loadResult(id: string) {
    const data = await fetchResult(id);
    setResult(data);
    if (data.state) {
      const info = await fetchRebuttalInfo(id).catch(() => null);
      setRebuttalInfo(info);
    }
  }

  function listenProgress(id: string) {
    const source = openProgressStream(id, async (event) => {
      setEvents((prev) => [...prev, event]);
      if (event.node === "__error__") {
        setError(event.status);
        source.close();
      }
      if (event.node === "__all__") {
        source.close();
        await loadResult(id);
        await refreshHistory();
      }
    });
  }

  async function handleUpload() {
    if (!file) {
      setError("请选择 .txt 或 .pdf 文件");
      return;
    }
    setBusy(true);
    setError("");
    setEvents([]);
    setResult(null);
    try {
      const data = await uploadPaper(file);
      setThreadId(data.thread_id);
      listenProgress(data.thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitRebuttal() {
    if (!threadId || !rebuttalText.trim()) {
      setError("请填写 Rebuttal 内容");
      return;
    }
    setBusy(true);
    setError("");
    setEvents([]);
    try {
      await submitRebuttal(threadId, target, rebuttalText);
      setRebuttalText("");
      listenProgress(threadId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function openHistory(id: string) {
    setThreadId(id);
    setEvents([]);
    setError("");
    await loadResult(id);
  }

  useEffect(() => {
    refreshHistory().catch(() => setHistory([]));
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">LangGraph Peer Review Agent</p>
          <h1>AI 论文审稿控制台</h1>
        </div>
        <span className="status-pill">{progressLabel}</span>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="layout-grid">
        <div className="main-column">
          <section className="panel">
            <h2>论文上传</h2>
            <div className="upload-row">
              <input type="file" accept=".txt,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <button onClick={handleUpload} disabled={busy}>{busy ? "处理中" : "开始审稿"}</button>
            </div>
            {threadId && <p className="muted">thread_id: {threadId}</p>}
          </section>

          <section className="panel">
            <h2>审稿进度</h2>
            <ol className="timeline">
              {events.filter((event) => !event.node.startsWith("__")).map((event, index) => (
                <li key={`${event.node}-${index}`}>
                  <span>{event.label ?? event.node}</span>
                  <small>{event.status}</small>
                </li>
              ))}
            </ol>
            {events.length === 0 && <p className="muted">上传论文后将显示实时节点进度。</p>}
          </section>

          {result && (
            <section className="panel">
              <h2>编辑决定</h2>
              <p className="decision">{renderValue(state?.editorial_decision)}</p>
              <pre>{renderValue(state?.dimension_scores)}</pre>
            </section>
          )}

          {result && (
            <section className="report-grid">
              {reviewerReports.map(([key, label]) => (
                <article className="report-card" key={key}>
                  <h3>{label}</h3>
                  <pre>{renderValue(state?.[key])}</pre>
                </article>
              ))}
            </section>
          )}
        </div>

        <aside className="side-column">
          <section className="panel">
            <h2>Rebuttal</h2>
            <select value={target} onChange={(event) => setTarget(event.target.value)} disabled={result?.locked}>
              <option value="all">全部审稿人</option>
              {(rebuttalInfo?.reviewers ?? []).map((reviewer) => (
                <option key={String(reviewer.role)} value={String(reviewer.role)}>{reviewer.name ?? reviewer.role}</option>
              ))}
            </select>
            <textarea value={rebuttalText} onChange={(event) => setRebuttalText(event.target.value)} disabled={result?.locked} rows={8} />
            <button onClick={handleSubmitRebuttal} disabled={busy || !result || result.locked}>
              {result?.locked ? "二审已完成" : "提交 Rebuttal"}
            </button>
          </section>

          <section className="panel">
            <h2>历史记录</h2>
            <div className="history-list">
              {history.map((item) => (
                <button key={item.thread_id} onClick={() => openHistory(item.thread_id)}>{item.thread_id}</button>
              ))}
            </div>
            {history.length === 0 && <p className="muted">暂无历史记录。</p>}
          </section>
        </aside>
      </section>
    </main>
  );
}
