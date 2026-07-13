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
