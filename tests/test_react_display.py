from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def read_frontend(path: str) -> str:
    return (ROOT / "frontend" / "src" / path).read_text(encoding="utf-8")


def test_reviewer_reports_render_as_sections_not_raw_json():
    app = read_frontend("App.tsx")

    assert "function ReportCard" in app
    assert "function ScoreGrid" in app
    assert "function TextList" in app
    assert "<pre>{renderValue(state?.[key])}</pre>" not in app


def test_history_items_render_paper_title_before_thread_id():
    app = read_frontend("App.tsx")
    types = read_frontend("types.ts")

    assert "type HistoryItem" in types
    assert "title?: string" in types
    assert "history-title" in app
    assert "item.title || \"未命名论文\"" in app


def test_home_brand_is_agent_reviewer_without_old_title():
    app = read_frontend("App.tsx")
    index = (ROOT / "frontend" / "index.html").read_text(encoding="utf-8")

    assert "AgentReviewer" in app
    assert "<title>AgentReviewer</title>" in index
    assert 'rel="icon"' in index
    assert "data:image/svg+xml" in index
    assert "AI 论文审稿控制台" not in app
    assert "<title>AI 论文审稿系统</title>" not in index


def test_reviewer_reports_are_paginated_one_reviewer_per_page():
    app = read_frontend("App.tsx")

    assert "function ReviewerPager" in app
    assert "reviewerPage" in app
    assert "上一位" in app
    assert "下一位" in app
    assert "reviewerReports.map(([key, label])" not in app


def test_editor_decision_shows_integrated_revision_issues():
    app = read_frontend("App.tsx")

    assert "function FinalIssueSummary" in app
    assert "function renderFinalIssue" in app
    assert "编辑综合修改问题" in app
    assert "revision_roadmap" in app
    assert "why_it_matters" in app
    assert "revision_direction" in app
    assert "effort" not in app
    assert "给作者的问题" not in app


def test_editor_decision_starts_with_collapsed_scoring_logic_explanation():
    app = read_frontend("App.tsx")
    css = read_frontend("styles.css")

    assert "function ScoringLogicDisclosure" in app
    assert '<details className="scoring-logic">' in app
    assert '<summary className="scoring-logic-summary">' in app
    assert "评分逻辑说明" in app
    assert "普通评审人平衡评分｜魔鬼评审人仅压力测试｜综合编辑校准" in app
    assert "原创性 20%" in app
    assert "方法 25%" in app
    assert "证据 25%" in app
    assert "结构 15%" in app
    assert "写作 15%" in app
    assert app.index("<ScoringLogicDisclosure />") < app.index("<h2>综合编辑决定</h2>")
    assert ".scoring-logic[open]" in css


def test_editor_decision_is_a_traceable_panel():
    app = read_frontend("App.tsx")
    css = read_frontend("styles.css")
    types = read_frontend("types.ts")

    assert "type DecisionTrace" in types
    assert "decision_trace?: DecisionTrace" in types
    assert "function EditorDecisionPanel" in app
    assert "function DecisionTracePanel" in app
    assert "<EditorDecisionPanel state={state} />" in app
    assert "决策依据" in app
    assert "普通评审人推荐" in app
    assert "魔鬼评审人压力测试" in app
    assert "规则校准" in app
    assert "reviewer_recommendations" in app
    assert "reviewer_weighted_scores" in app
    assert "Editor-in-Chief" not in app
    assert "DA 压力测试" not in app
    assert "CRITICAL 数量" not in app
    assert ".editor-decision-panel" in css
    assert ".decision-trace" in css


def test_editor_decision_loads_after_synthesis_and_uses_bilingual_labels():
    """A completed synthesizer step must populate a bilingual final decision."""
    app = read_frontend("App.tsx")

    assert 'if (event.node === "synthesizer")' in app
    assert 'await loadResult(id);' in app
    assert 'Accept: "接收（ACCEPT）"' in app
    assert '"Minor Revision": "小修（MINOR REVISION）"' in app
    assert '"Major Revision": "大修（MAJOR REVISION）"' in app
    assert 'Reject: "拒稿（REJECT）"' in app


def test_console_navigation_keeps_rebuttal_inside_review_workspace():
    app = read_frontend("App.tsx")

    assert "type ActiveView" in app
    assert "审稿台" in app
    assert "历史记录" in app
    assert "设置" in app
    assert "Rebuttal" in app
    assert '"rebuttal"' not in app


def test_settings_page_exposes_llm_and_embedding_config():
    app = read_frontend("App.tsx")
    api = read_frontend("api.ts")
    types = read_frontend("types.ts")

    assert "function SettingsPanel" in app
    assert "审稿 LLM" in app
    assert "Embedding 模型" in app
    assert "REVIEW_LLM_BASE_URL" in app
    assert "REVIEW_LLM_MODEL" in app
    assert "EMBEDDING_BASE_URL" in app
    assert "EMBEDDING_MODEL" in app
    assert "MIMO_BASE_URL" not in app
    assert "GITEE_BASE_URL" not in app
    assert "fetchSettings" in api
    assert "saveSettings" in api
    assert "type SettingsPayload" in types


def test_review_workspace_shows_rag_embedding_diagnostics():
    app = read_frontend("App.tsx")
    types = read_frontend("types.ts")
    css = read_frontend("styles.css")

    assert "type RagDiagnostics" in types
    assert "rag_diagnostics" in types
    assert "function RagDiagnosticsPanel" in app
    assert "RAG 状态" in app
    assert "chunk_count" in app
    assert "embedding_batches" in app
    assert "chunk_embedding_status" in app
    assert ".rag-diagnostics" in css


def test_rag_diagnostics_are_collapsed_inside_progress_panel():
    app = read_frontend("App.tsx")
    css = read_frontend("styles.css")

    assert 'className="panel progress-panel"' in app
    assert '<details className="rag-diagnostics">' in app
    assert '<summary className="rag-diagnostics-summary">' in app
    assert "{result?.rag_diagnostics && <RagDiagnosticsPanel diagnostics={result.rag_diagnostics} />}" in app
    assert "{result && <RagDiagnosticsPanel diagnostics={result.rag_diagnostics} />}" not in app
    assert ".rag-diagnostics[open]" in css


def test_history_result_restores_progress_timeline_from_saved_done_nodes():
    app = read_frontend("App.tsx")
    types = read_frontend("types.ts")

    assert "done?: string[]" in types
    assert "const progressNodeLabels" in app
    assert "function progressEventsFromResult" in app
    assert "setEvents((prev) => prev.length > 0 ? prev : restoredEvents);" in app


def test_frontend_exposes_continue_review_button():
    app = read_frontend("App.tsx")
    api = read_frontend("api.ts")
    types = read_frontend("types.ts")

    assert "resumeReview" in api
    assert "can_resume" in types
    assert "handleResumeReview" in app
    assert "继续审稿" in app
    assert "/api/resume/" in api


def test_console_style_uses_reference_like_black_and_white_shell():
    css = read_frontend("styles.css")

    assert ".console-nav" in css
    assert ".hero-row" in css
    assert ".settings-grid" in css
    assert "background: #fff" in css
    assert "border: 1px solid #e5e5e5" in css
    assert "background: #0b0b0b" in css
