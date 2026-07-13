# tests/test_checkpoint.py
import tempfile, os
import pytest
from types import SimpleNamespace
import paper_reviewer.checkpoint as checkpoint
from paper_reviewer.checkpoint import get_checkpointer, get_thread_state, list_threads
from paper_reviewer.state import ReviewState


class TestReviewStateExtended:
    def test_state_has_round_number(self):
        """State 扩展后应包含 round_number 字段"""
        state = ReviewState(
            paper="x", paper_title="t", language="zh",
            rag_index=None, primary_discipline="", secondary_disciplines=[],
            research_paradigm="", methodology_type="", target_journal_tier="",
            reviewer_configs=[], eic_report=None, methodology_report=None,
            domain_report=None, perspective_report=None, devils_advocate_report=None,
            editorial_decision="", consensus_analysis=None, dimension_scores=None,
            revision_roadmap=None,
            round_number=1, rebuttal_text=None, rebuttal_target=None, rebuttal_history=[],
        )
        assert state["round_number"] == 1
        assert state["rebuttal_text"] is None

    def test_state_default_round_is_1(self):
        """字典形式时 round_number 默认 1"""
        d = {"paper": "x", "paper_title": "t", "language": "zh"}
        assert d.get("round_number", 1) == 1


class TestCheckpointer:
    def test_returns_sqlite_saver(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            cp = get_checkpointer(db)
            assert cp is not None

    def test_get_thread_state_returns_none_for_unknown(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            assert get_thread_state("nonexistent", db) is None

    def test_list_threads_empty_initially(self):
        with tempfile.TemporaryDirectory() as tmp:
            db = os.path.join(tmp, "test.db")
            assert list_threads(db) == []

    def test_list_threads_deduplicates_checkpoint_history(self, monkeypatch):
        class FakeCheckpointer:
            def __init__(self):
                self.released = False

            def list(self, _config):
                return [
                    SimpleNamespace(config={"configurable": {"thread_id": "t1"}}),
                    SimpleNamespace(config={"configurable": {"thread_id": "t2"}}),
                    SimpleNamespace(config={"configurable": {"thread_id": "t1"}}),
                ]

            def release(self):
                self.released = True

        fake = FakeCheckpointer()
        monkeypatch.setattr(checkpoint, "get_checkpointer", lambda _db_path: fake)

        assert list_threads("ignored.db") == [{"thread_id": "t1"}, {"thread_id": "t2"}]
        assert fake.released is True
