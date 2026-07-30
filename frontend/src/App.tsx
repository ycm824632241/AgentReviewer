import { useEffect, useMemo, useRef, useState } from "react";
import type { ReactNode } from "react";
import { fetchHistory, fetchResult, fetchRebuttalInfo, fetchSettings, openProgressStream, saveSettings, submitRebuttal, uploadPaper } from "./api";
import type { DecisionTrace, HistoryItem, ProgressEvent, RagDiagnostics, RebuttalInfoResponse, ReviewResultResponse, ReviewState, SettingsPayload, SettingsUpdate } from "./types";

const reviewerReports: Array<[keyof ReviewState, string]> = [
  ["eic_report", "主编视角评审人"],
  ["methodology_report", "方法论专家"],
  ["domain_report", "领域专家"],
  ["perspective_report", "跨学科视角"],
  ["devils_advocate_report", "魔鬼评审人"]
];

type ActiveStream = {
  threadId: string;
  source: EventSource;
};

type RecordValue = Record<string, unknown>;
type ActiveView = "review" | "history" | "settings";

const scoreLabels: Record<string, string> = {
  originality: "原创性",
  methodology: "方法",
  evidence: "证据",
  coherence: "结构",
  writing: "写作",
  weighted_total: "加权总分",
  weighted_average: "加权平均"
};

const decisionLabels: Record<string, string> = {
  Accept: "接收",
  "Minor Revision": "小修",
  "Major Revision": "大修",
  Reject: "拒稿"
};

const progressNodeLabels: Record<string, string> = {
  field_analyst: "领域分析",
  eic: "主编视角评审",
  methodology: "方法论审稿",
  domain: "领域专家审稿",
  perspective: "跨学科审稿",
  devils_advocate: "魔鬼评审人压力测试",
  rebuttal_eic: "主编视角二审",
  rebuttal_methodology: "方法论二审",
  rebuttal_domain: "领域专家二审",
  rebuttal_perspective: "跨学科二审",
  rebuttal_devils_advocate: "魔鬼评审人二审",
  synthesizer: "编辑综合"
};

function progressEventsFromResult(data: ReviewResultResponse): ProgressEvent[] {
  const done = Array.isArray(data.progress.done) ? data.progress.done : [];
  return done
    .filter((node): node is string => typeof node === "string" && !node.startsWith("__"))
    .map((node) => ({
      node,
      label: progressNodeLabels[node] ?? node,
      status: "done"
    }));
}

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

function renderDecisionValue(value: unknown): string {
  if (typeof value !== "string") return renderValue(value);
  return decisionLabels[value] ?? value;
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

function cleanIssueText(value: unknown): string {
  return renderValue(value).replace(/（?预计[:：]?\s*[^）)]*[天日周月][）)]?/g, "").trim();
}

function renderFinalIssue(item: unknown): string {
  if (!isRecord(item)) return cleanIssueText(item);

  const issue = getField(item, ["issue", "item", "title", "description", "problem"]);
  const why = getField(item, ["why_it_matters"]);
  const direction = getField(item, ["revision_direction", "suggestion"]);
  const parts = [
    issue ? cleanIssueText(issue) : "",
    why ? `影响：${cleanIssueText(why)}` : "",
    direction ? `修改方向：${cleanIssueText(direction)}` : ""
  ].filter(Boolean);

  return parts.length > 0 ? parts.join("。") : cleanIssueText(item);
}

function FinalIssueSummary({ roadmap }: { roadmap: unknown }) {
  if (!isRecord(roadmap)) return <p className="muted">暂无编辑综合修改问题。</p>;

  const integratedIssues = getField(roadmap, ["integrated_paper_issues", "issues", "problems"]);
  const fallbackIssues = Object.entries(roadmap)
    .filter(([key]) => key !== "integrated_paper_issues")
    .flatMap(([, value]) => asList(value));
  const issues = asList(integratedIssues).length > 0 ? integratedIssues : fallbackIssues;

  return (
    <section className="final-issues">
      <h3>编辑综合修改问题</h3>
      <ul className="text-list">
        {asList(issues).map((item, index) => (
          <li key={index}>{renderFinalIssue(item)}</li>
        ))}
      </ul>
    </section>
  );
}

function ScoringLogicDisclosure() {
  return (
    <details className="scoring-logic">
      <summary className="scoring-logic-summary">
        <span className="scoring-logic-title">评分逻辑说明</span>
        <span className="scoring-logic-note">普通评审人平衡评分｜魔鬼评审人仅压力测试｜综合编辑校准</span>
      </summary>
      <ul className="scoring-logic-list">
        <li>普通评审人：主编视角评审人、方法论、领域、跨学科会同时给出优点、问题、推荐决定和五维评分。</li>
        <li>五维权重：原创性 20%、方法 25%、证据 25%、结构 15%、写作 15%。</li>
        <li>魔鬼评审人：不打分，只做压力测试和风险提示，不参与最终评分或录用决定。</li>
        <li>综合编辑：不是简单平均，而是综合普通评审报告后输出最终决定和最终五维评分，并做规则校准。</li>
      </ul>
    </details>
  );
}

function renderDecisionRecord(record: Record<string, string | number> | undefined): string {
  if (!record || Object.keys(record).length === 0) return "暂无";
  return Object.entries(record).map(([role, value]) => `${role}：${renderDecisionValue(value)}`).join("；");
}

function DecisionTracePanel({ trace }: { trace?: DecisionTrace }) {
  if (!trace) {
    return (
      <section className="decision-trace">
        <h3>决策依据</h3>
        <p className="muted">暂无本次决策轨迹。</p>
      </section>
    );
  }

  return (
    <section className="decision-trace">
      <h3>决策依据</h3>
      <p className="decision-summary">{renderValue(trace.decision_summary)}</p>
      <dl className="decision-trace-grid">
        <div>
          <dt>普通评审人推荐</dt>
          <dd>{renderDecisionRecord(trace.reviewer_recommendations)}</dd>
        </div>
        <div>
          <dt>普通评审人加权分</dt>
          <dd>{renderDecisionRecord(trace.reviewer_weighted_scores)}</dd>
        </div>
        <div>
          <dt>魔鬼评审人压力测试</dt>
          <dd>关键风险数量：{renderValue(trace.da_critical_count)}</dd>
        </div>
        <div>
          <dt>规则校准</dt>
          <dd>{asList(trace.applied_rules).length > 0 ? renderValue(trace.applied_rules) : "未触发硬性校准规则"}</dd>
        </div>
      </dl>
      {trace.decision_rationale && <p className="muted">综合编辑说明：{trace.decision_rationale}</p>}
    </section>
  );
}

function EditorDecisionPanel({ state }: { state?: ReviewState | null }) {
  return (
    <section className="panel editor-decision-panel">
      <ScoringLogicDisclosure />
      <div className="panel-heading">
        <div>
          <h2>综合编辑决定</h2>
          <p className="muted">单独汇总最终决定、评分和本次决策轨迹。</p>
        </div>
        <span className="status-pill">{renderDecisionValue(state?.editorial_decision)}</span>
      </div>
      <p className="decision">{renderDecisionValue(state?.editorial_decision)}</p>
      <DecisionTracePanel trace={state?.decision_trace} />
      <ReportSection title="五维最终评分">
        <ScoreGrid scores={state?.dimension_scores} />
      </ReportSection>
      <FinalIssueSummary roadmap={state?.revision_roadmap} />
    </section>
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
  const counterArgument = getField(report, ["strongest_counter_argument"]);
  const alternatives = getField(report, ["ignored_alternatives"]);
  const stakeholders = getField(report, ["missing_stakeholders"]);
  const premise = getField(report, ["unexamined_premise"]);

  return (
    <article className="report-card">
      <div className="report-card-header">
        <h3>{label}</h3>
        {Boolean(recommendation) && <span className="recommendation-chip">{renderDecisionValue(recommendation)}</span>}
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

function ReviewerPager({
  page,
  onPageChange,
  state
}: {
  page: number;
  onPageChange: (page: number) => void;
  state?: ReviewState;
}) {
  const safePage = Math.min(Math.max(page, 0), reviewerReports.length - 1);
  const [key, label] = reviewerReports[safePage];

  return (
    <section className="reviewer-pager">
      <div className="pager-toolbar">
        <button onClick={() => onPageChange(Math.max(0, safePage - 1))} disabled={safePage === 0}>
          上一位
        </button>
        <span>{safePage + 1} / {reviewerReports.length}</span>
        <button onClick={() => onPageChange(Math.min(reviewerReports.length - 1, safePage + 1))} disabled={safePage === reviewerReports.length - 1}>
          下一位
        </button>
      </div>
      <div className="pager-tabs" aria-label="审稿人分页">
        {reviewerReports.map(([, reviewerLabel], index) => (
          <button
            className={index === safePage ? "active" : ""}
            key={reviewerLabel}
            onClick={() => onPageChange(index)}
          >
            {reviewerLabel}
          </button>
        ))}
      </div>
      <ReportCard label={label} report={state?.[key]} />
    </section>
  );
}

function ragStatusLabel(status?: string): string {
  if (status === "success") return "全文索引已完成";
  if (status === "failed") return "全文索引失败";
  if (status === "not_built") return "尚未建立索引";
  if (status === "skipped_single_chunk") return "单块文本，无需向量检索";
  return "等待索引状态";
}

function ragSummary(diagnostics: RagDiagnostics): string {
  if (diagnostics.enabled === false) {
    return diagnostics.reason === "paper_too_short" ? "论文较短，未启用向量检索" : "未启用";
  }

  const status = ragStatusLabel(diagnostics.chunk_embedding_status);
  const chunkCount = diagnostics.chunk_count ? `${diagnostics.chunk_count} chunks` : "等待分块";
  const cache = diagnostics.cache_hit ? "缓存命中" : "未命中缓存";
  const fallback = diagnostics.fallback_used ? "查询已降级" : "查询未降级";
  return `${status}｜${chunkCount}｜${cache}｜${fallback}`;
}

function RagDiagnosticsPanel({ diagnostics }: { diagnostics?: RagDiagnostics | null }) {
  if (!diagnostics) return null;

  const rows = diagnostics.enabled === false
    ? [
        ["全文字符", renderValue(diagnostics.paper_chars)],
        ["RAG 状态", diagnostics.reason === "paper_too_short" ? "论文较短，未启用向量检索" : "未启用"]
      ]
    : [
        ["全文字符", renderValue(diagnostics.paper_chars)],
        ["分块数量", renderValue(diagnostics.chunk_count)],
        ["分块参数", `${renderValue(diagnostics.chunk_size)} 字 / overlap ${renderValue(diagnostics.chunk_overlap)}`],
        ["最大分块", `${renderValue(diagnostics.max_chunk_bytes)} / ${renderValue(diagnostics.chunk_max_bytes)} bytes`],
        ["Embedding 批次", renderValue(diagnostics.embedding_batches)],
        ["RAG 状态", ragStatusLabel(diagnostics.chunk_embedding_status)],
        ["查询降级", diagnostics.fallback_used ? `已触发 ${renderValue(diagnostics.query_embedding_failures)} 次` : "未触发"],
        ["缓存命中", diagnostics.cache_hit ? "是" : "否"]
      ];

  return (
    <details className="rag-diagnostics">
      <summary className="rag-diagnostics-summary">
        <span className="rag-diagnostics-title">RAG 状态</span>
        <span className="rag-diagnostics-note">{ragSummary(diagnostics)}</span>
      </summary>
      <p className="muted rag-diagnostics-description">用于确认论文是否完成分块索引，以及审稿检索是否退回到均匀抽样。</p>
      <dl>
        {rows.map(([label, value]) => (
          <div key={label}>
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {diagnostics.last_error && <p className="muted">最近错误：{diagnostics.last_error}</p>}
    </details>
  );
}

function SettingsField({
  label,
  envName,
  value,
  onChange,
  type = "text",
  placeholder = ""
}: {
  label: string;
  envName: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  placeholder?: string;
}) {
  return (
    <label className="settings-field">
      <span>{label}</span>
      <small>{envName}</small>
      <input type={type} value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} />
    </label>
  );
}

function SettingsPanel({
  settings,
  form,
  onFieldChange,
  onSave,
  busy,
  saved
}: {
  settings: SettingsPayload | null;
  form: SettingsUpdate;
  onFieldChange: (group: keyof SettingsUpdate, field: keyof SettingsUpdate["llm"], value: string) => void;
  onSave: () => void;
  busy: boolean;
  saved: boolean;
}) {
  const llmKeyPlaceholder = settings?.llm.api_key_set ? settings.llm.api_key : "未配置";
  const embeddingKeyPlaceholder = settings?.embedding.api_key_set ? settings.embedding.api_key : "未配置";

  return (
    <section className="panel settings-panel">
      <div className="panel-heading">
        <div>
          <h2>模型配置</h2>
          <p className="muted">保存后，新发起的审稿任务会使用新的模型连接参数。</p>
        </div>
        <span className="status-pill">{settings?.llm.api_key_set && settings?.embedding.api_key_set ? "已配置" : "未完整配置"}</span>
      </div>

      <div className="settings-grid">
        <section className="settings-card">
          <h3>审稿 LLM</h3>
          <SettingsField
            label="API Base URL"
            envName="REVIEW_LLM_BASE_URL"
            value={form.llm.base_url}
            onChange={(value) => onFieldChange("llm", "base_url", value)}
          />
          <SettingsField
            label="API Key"
            envName="REVIEW_LLM_API_KEY"
            type="password"
            value={form.llm.api_key}
            placeholder={llmKeyPlaceholder}
            onChange={(value) => onFieldChange("llm", "api_key", value)}
          />
          <SettingsField
            label="模型名称"
            envName="REVIEW_LLM_MODEL"
            value={form.llm.model}
            onChange={(value) => onFieldChange("llm", "model", value)}
          />
        </section>

        <section className="settings-card">
          <h3>Embedding 模型</h3>
          <SettingsField
            label="Embedding API Base URL"
            envName="EMBEDDING_BASE_URL"
            value={form.embedding.base_url}
            onChange={(value) => onFieldChange("embedding", "base_url", value)}
          />
          <SettingsField
            label="Embedding API Key"
            envName="EMBEDDING_API_KEY"
            type="password"
            value={form.embedding.api_key}
            placeholder={embeddingKeyPlaceholder}
            onChange={(value) => onFieldChange("embedding", "api_key", value)}
          />
          <SettingsField
            label="Embedding 模型名称"
            envName="EMBEDDING_MODEL"
            value={form.embedding.model}
            onChange={(value) => onFieldChange("embedding", "model", value)}
          />
        </section>
      </div>

      <div className="settings-actions">
        <button onClick={onSave} disabled={busy}>{busy ? "保存中" : "保存设置"}</button>
        {saved && <span className="saved-note">设置已保存</span>}
      </div>
    </section>
  );
}

export default function App() {
  const [activeView, setActiveView] = useState<ActiveView>("review");
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<ReviewResultResponse | null>(null);
  const [rebuttalInfo, setRebuttalInfo] = useState<RebuttalInfoResponse | null>(null);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [settings, setSettings] = useState<SettingsPayload | null>(null);
  const [settingsForm, setSettingsForm] = useState<SettingsUpdate>({
    llm: { base_url: "", api_key: "", model: "" },
    embedding: { base_url: "", api_key: "", model: "" }
  });
  const [target, setTarget] = useState("all");
  const [rebuttalText, setRebuttalText] = useState("");
  const [reviewerPage, setReviewerPage] = useState(0);
  const [busy, setBusy] = useState(false);
  const [settingsBusy, setSettingsBusy] = useState(false);
  const [settingsSaved, setSettingsSaved] = useState(false);
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

  async function refreshSettings() {
    const data = await fetchSettings();
    setSettings(data);
    setSettingsForm({
      llm: { base_url: data.llm.base_url, api_key: "", model: data.llm.model },
      embedding: { base_url: data.embedding.base_url, api_key: "", model: data.embedding.model }
    });
  }

  function updateSettingsField(group: keyof SettingsUpdate, field: keyof SettingsUpdate["llm"], value: string) {
    setSettingsSaved(false);
    setSettingsForm((prev) => ({
      ...prev,
      [group]: {
        ...prev[group],
        [field]: value
      }
    }));
  }

  async function handleSaveSettings() {
    setSettingsBusy(true);
    setError("");
    try {
      const data = await saveSettings(settingsForm);
      setSettings(data);
      setSettingsForm({
        llm: { base_url: data.llm.base_url, api_key: "", model: data.llm.model },
        embedding: { base_url: data.embedding.base_url, api_key: "", model: data.embedding.model }
      });
      setSettingsSaved(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "保存设置失败");
    } finally {
      setSettingsBusy(false);
    }
  }

  async function loadResult(id: string): Promise<ReviewResultResponse> {
    const data = await fetchResult(id);
    if (selectedThreadRef.current !== id) return data;

    setResult(data);
    setRebuttalInfo(null);
    const restoredEvents = progressEventsFromResult(data);
    if (restoredEvents.length > 0) {
      setEvents((prev) => prev.length > 0 ? prev : restoredEvents);
    }
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
    setActiveView("review");
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
    refreshSettings().catch((err) => setError(err instanceof Error ? err.message : "读取设置失败"));
    return () => {
      const active = activeStreamRef.current;
      active?.source.close();
      activeStreamRef.current = null;
    };
  }, []);

  useEffect(() => {
    setReviewerPage(0);
  }, [result?.thread_id]);

  return (
    <main className="app-shell">
      <header className="console-nav">
        <button className="brand-button" onClick={() => setActiveView("review")}>
          <span className="brand-dot" />
          AgentReviewer
        </button>
        <nav className="nav-tabs" aria-label="主导航">
          <button className={activeView === "review" ? "active" : ""} onClick={() => setActiveView("review")}>审稿台</button>
          <button className={activeView === "history" ? "active" : ""} onClick={() => setActiveView("history")}>历史记录</button>
          <button className={activeView === "settings" ? "active" : ""} onClick={() => setActiveView("settings")}>设置</button>
        </nav>
        <button className="nav-more" aria-label="更多">...</button>
      </header>

      <section className="hero-row">
        <div>
          <h1>{activeView === "settings" ? "设置" : activeView === "history" ? "历史记录" : "审稿台"}</h1>
          <p className="muted">
            {activeView === "settings"
              ? "配置审稿 LLM 与 Embedding 模型连接参数。"
              : activeView === "history"
                ? "查看历史审稿线程，点击任意论文回到审稿台继续查看。"
                : "上传论文后，系统会并行生成多角色审稿意见，并由编辑综合最终决定。"}
          </p>
        </div>
        <span className="status-pill">{progressLabel}</span>
      </section>

      {error && <div className="error-banner">{error}</div>}

      {activeView === "review" && <section className="layout-grid">
        <div className="main-column">
          <section className="panel">
            <h2>论文上传</h2>
            <div className="upload-row">
              <input type="file" accept=".txt,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} disabled={busy} />
              <button onClick={handleUpload} disabled={busy}>{busy ? "处理中" : "开始审稿"}</button>
            </div>
            {threadId && <p className="muted">thread_id: {threadId}</p>}
          </section>

          <section className="panel progress-panel">
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
            {result?.rag_diagnostics && <RagDiagnosticsPanel diagnostics={result.rag_diagnostics} />}
          </section>

          {result && (
            <EditorDecisionPanel state={state} />
          )}

          {result && (
            <ReviewerPager page={reviewerPage} onPageChange={setReviewerPage} state={state ?? undefined} />
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
        </aside>
      </section>}

      {activeView === "history" && (
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>历史记录</h2>
              <p className="muted">按论文标题展示历史任务，点击后加载对应 thread。</p>
            </div>
          </div>
          <div className="history-list history-page-list">
            {history.map((item) => (
              <button key={item.thread_id} onClick={() => openHistory(item.thread_id)}>
                <span className="history-title">{item.title || "未命名论文"}</span>
                <small>{item.thread_id}</small>
              </button>
            ))}
          </div>
          {history.length === 0 && <p className="muted">暂无历史记录。</p>}
        </section>
      )}

      {activeView === "settings" && (
        <SettingsPanel
          settings={settings}
          form={settingsForm}
          onFieldChange={updateSettingsField}
          onSave={handleSaveSettings}
          busy={settingsBusy}
          saved={settingsSaved}
        />
      )}
    </main>
  );
}
