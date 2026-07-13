import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { fetchHistory, fetchResult, fetchRebuttalInfo, openProgressStream, submitRebuttal, uploadPaper } from "./api";
import type { HistoryItem, ProgressEvent, RebuttalInfoResponse, ReviewResultResponse, ReviewState } from "./types";

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

type RecordValue = Record<string, unknown>;

const scoreLabels: Record<string, string> = {
  originality: "原创性",
  methodology: "方法",
  evidence: "证据",
  coherence: "结构",
  writing: "写作",
  weighted_total: "加权总分",
  weighted_average: "加权平均"
};

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  if (Array.isArray(value)) return value.map(renderValue).join("；");
  if (isRecord(value)) {
    return Object.entries(value)
      .map(([key, item]) => `${labelize(key)}：${renderValue(item)}`)
      .join("；");
  }
  return String(value);
}

function isRecord(value: unknown): value is RecordValue {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function labelize(key: string): string {
  return scoreLabels[key] ?? key.replace(/_/g, " ");
}

function getField(report: RecordValue, keys: string[]): unknown {
  return keys.map((key) => report[key]).find((value) => value !== undefined && value !== null && value !== "");
}

function asList(value: unknown): unknown[] {
  if (value === null || value === undefined || value === "") return [];
  return Array.isArray(value) ? value : [value];
}

function ScoreGrid({ scores }: { scores: unknown }) {
  if (!isRecord(scores)) return <p className="muted">暂无评分。</p>;
  const entries = Object.entries(scores).filter(([, value]) => typeof value === "number" || typeof value === "string");
  if (entries.length === 0) return <p className="muted">暂无评分。</p>;

  return (
    <dl className="score-grid">
      {entries.map(([key, value]) => (
        <div key={key}>
          <dt>{labelize(key)}</dt>
          <dd>{renderValue(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function TextList({ value }: { value: unknown }) {
  const items = asList(value);
  if (items.length === 0) return <p className="muted">暂无。</p>;

  return (
    <ul className="text-list">
      {items.map((item, index) => (
        <li key={index}>{renderValue(item)}</li>
      ))}
    </ul>
  );
}

function ReportSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="report-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function ReportCard({ label, report }: { label: string; report: unknown }) {
  if (!isRecord(report)) {
    return (
      <article className="report-card">
        <h3>{label}</h3>
        <p className="muted">暂无审稿意见。</p>
      </article>
    );
  }

  const recommendation = getField(report, ["recommendation", "decision"]);
  const confidence = getField(report, ["confidence"]);
  const scores = getField(report, ["dimension_scores", "scores"]);
  const strengths = getField(report, ["strengths"]);
  const weaknesses = getField(report, ["weaknesses", "issues"]);
  const questions = getField(report, ["questions_for_author", "questions"]);
  const counterArgument = getField(report, ["strongest_counter_argument"]);
  const alternatives = getField(report, ["ignored_alternatives"]);
  const stakeholders = getField(report, ["missing_stakeholders"]);
  const premise = getField(report, ["unexamined_premise"]);

  return (
    <article className="report-card">
      <div className="report-card-header">
        <h3>{label}</h3>
        {Boolean(recommendation) && <span className="recommendation-chip">{renderValue(recommendation)}</span>}
      </div>

      <div className="report-meta">
        <span>置信度：{confidence ? `${renderValue(confidence)}/5` : "暂无"}</span>
      </div>

      <ReportSection title="维度评分">
        <ScoreGrid scores={scores} />
      </ReportSection>

      <ReportSection title="主要优点">
        <TextList value={strengths} />
      </ReportSection>

      <ReportSection title="主要问题">
        <TextList value={weaknesses} />
      </ReportSection>

      <ReportSection title="给作者的问题">
        <TextList value={questions} />
      </ReportSection>

      {Boolean(counterArgument || alternatives || stakeholders || premise) && (
        <ReportSection title="反向论证">
          {Boolean(counterArgument) && <p>{renderValue(counterArgument)}</p>}
          {Boolean(alternatives) && <TextList value={alternatives} />}
          {Boolean(stakeholders) && <TextList value={stakeholders} />}
          {Boolean(premise) && <p>{renderValue(premise)}</p>}
        </ReportSection>
      )}
    </article>
  );
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<ReviewResultResponse | null>(null);
  const [rebuttalInfo, setRebuttalInfo] = useState<RebuttalInfoResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [target, setTarget] = useState("all");
  const [rebuttalText, setRebuttalText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const activeStreamRef = useRef<ActiveStream | null>(null);
  const selectedThreadRef = useRef("");

  const finished = events.some((event) => event.node === "__all__") || result?.progress.finished === true;
  const failed = events.some((event) => event.node === "__error__") || Boolean(result?.progress.error);
  const state = result?.state;

  const progressLabel = useMemo(() => {
    if (!threadId) return "等待上传";
    if (failed) return "审稿失败";
    if (finished) return "审稿完成";
    return "审稿进行中";
  }, [failed, finished, threadId]);

  async function refreshHistory() {
    const data = await fetchHistory();
    setHistory(data.threads);
  }

  async function loadResult(id: string): Promise<ReviewResultResponse> {
    const data = await fetchResult(id);
    if (selectedThreadRef.current !== id) return data;

    setResult(data);
    setRebuttalInfo(null);
    if (!data.state) return data;

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
    return data;
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
      const data = await loadResult(id);
      if (selectedThreadRef.current !== id) return;
      if (!data.progress.finished && !data.progress.error) {
        listenProgress(id);
      }
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
          <h1>AgentReviewer</h1>
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
              <ScoreGrid scores={state?.dimension_scores} />
            </section>
          )}

          {result && (
            <section className="report-grid">
              {reviewerReports.map(([key, label]) => (
                <ReportCard key={key} label={label} report={state?.[key]} />
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
                <option key={reviewer.target} value={reviewer.target}>{reviewer.name ?? reviewer.role ?? reviewer.target}</option>
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
                <button key={item.thread_id} onClick={() => openHistory(item.thread_id)}>
                  <span className="history-title">{item.title || "未命名论文"}</span>
                  <small>{item.thread_id}</small>
                </button>
              ))}
            </div>
            {history.length === 0 && <p className="muted">暂无历史记录。</p>}
          </section>
        </aside>
      </section>
    </main>
  );
}
