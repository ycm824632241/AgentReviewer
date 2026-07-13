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
