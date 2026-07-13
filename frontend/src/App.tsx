import { useEffect, useMemo, useRef, useState } from "react";
import { fetchHistory, fetchResult, fetchRebuttalInfo, openProgressStream, submitRebuttal, uploadPaper } from "./api";
import type { ProgressEvent, RebuttalInfoResponse, ReviewResultResponse, ReviewState } from "./types";

const reviewerReports: Array<[keyof ReviewState, string]> = [
  ["eic_report", "Editor-in-Chief"],
  ["methodology_report", "方法论专家"],
  ["domain_report", "领域专家"],
  ["perspective_report", "跨学科视角"],
  ["devils_advocate_report", "Devil's Advocate"]
];

type ActiveStream = {
  threadId: string;
  source: EventSource;
};

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
  const activeStreamRef = useRef<ActiveStream | null>(null);
  const selectedThreadRef = useRef("");

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
    if (selectedThreadRef.current !== id) return;

    setResult(data);
    setRebuttalInfo(null);
    if (!data.state) return;

    try {
      const info = await fetchRebuttalInfo(id);
      if (selectedThreadRef.current === id) {
        setRebuttalInfo(info);
      }
    } catch (err) {
      if (selectedThreadRef.current === id) {
        setError(err instanceof Error ? err.message : "读取 Rebuttal 信息失败");
      }
    }
  }

  function isActiveStream(id: string, source: EventSource) {
    const active = activeStreamRef.current;
    return active?.threadId === id && active.source === source && selectedThreadRef.current === id;
  }

  function stopActiveStream(source?: EventSource) {
    const active = activeStreamRef.current;
    if (!active || (source && active.source !== source)) return;

    active.source.close();
    activeStreamRef.current = null;
    setBusy(false);
  }

  function listenProgress(id: string) {
    stopActiveStream();
    setBusy(true);

    const source = openProgressStream(id, (event) => {
      void handleProgressEvent(id, source, event).catch((err) => {
        if (!isActiveStream(id, source)) return;
        setError(err instanceof Error ? err.message : "读取审稿进度失败");
        stopActiveStream(source);
      });
    });
    activeStreamRef.current = { threadId: id, source };
    source.onerror = () => {
      if (!isActiveStream(id, source)) return;
      setError("审稿进度连接已中断");
      stopActiveStream(source);
    };
  }

  async function handleProgressEvent(id: string, source: EventSource, event: ProgressEvent) {
    if (!isActiveStream(id, source)) return;

    setEvents((prev) => [...prev, event]);
    if (event.node === "__error__") {
      setError(event.status);
      stopActiveStream(source);
      return;
    }
    if (event.node === "__all__") {
      stopActiveStream(source);
      try {
        await loadResult(id);
        await refreshHistory();
      } catch (err) {
        if (selectedThreadRef.current === id) {
          setError(err instanceof Error ? err.message : "读取审稿结果失败");
        }
      }
    }
  }

  async function handleUpload() {
    if (!file) {
      setError("请选择 .txt 或 .pdf 文件");
      return;
    }
    stopActiveStream();
    setBusy(true);
    setError("");
    setEvents([]);
    setResult(null);
    setRebuttalInfo(null);
    selectedThreadRef.current = "";
    setThreadId("");
    try {
      const data = await uploadPaper(file);
      if (selectedThreadRef.current !== "") {
        setBusy(false);
        return;
      }
      selectedThreadRef.current = data.thread_id;
      setThreadId(data.thread_id);
      listenProgress(data.thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
      setBusy(false);
    }
  }

  async function handleSubmitRebuttal() {
    if (!threadId || !rebuttalText.trim()) {
      setError("请填写 Rebuttal 内容");
      return;
    }
    const id = threadId;
    stopActiveStream();
    setBusy(true);
    setError("");
    setEvents([]);
    try {
      await submitRebuttal(id, target, rebuttalText);
      if (selectedThreadRef.current !== id) {
        setBusy(false);
        return;
      }
      setRebuttalText("");
      listenProgress(id);
    } catch (err) {
      if (selectedThreadRef.current === id) {
        setError(err instanceof Error ? err.message : "提交失败");
      }
      setBusy(false);
    }
  }

  async function openHistory(id: string) {
    stopActiveStream();
    selectedThreadRef.current = id;
    setThreadId(id);
    setEvents([]);
    setError("");
    setResult(null);
    setRebuttalInfo(null);
    try {
      await loadResult(id);
    } catch (err) {
      if (selectedThreadRef.current === id) {
        setError(err instanceof Error ? err.message : "读取审稿结果失败");
      }
    }
  }

  useEffect(() => {
    refreshHistory().catch((err) => setError(err instanceof Error ? err.message : "读取历史记录失败"));
    return () => {
      const active = activeStreamRef.current;
      active?.source.close();
      activeStreamRef.current = null;
    };
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
              <input type="file" accept=".txt,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} disabled={busy} />
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
            <select value={target} onChange={(event) => setTarget(event.target.value)} disabled={busy || result?.locked}>
              <option value="all">全部审稿人</option>
              {(rebuttalInfo?.reviewers ?? []).map((reviewer) => (
                <option key={String(reviewer.role)} value={String(reviewer.role)}>{reviewer.name ?? reviewer.role}</option>
              ))}
            </select>
            <textarea value={rebuttalText} onChange={(event) => setRebuttalText(event.target.value)} disabled={busy || result?.locked} rows={8} />
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
