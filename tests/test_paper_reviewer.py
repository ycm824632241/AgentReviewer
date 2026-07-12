import pytest
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from paper_reviewer.state import ReviewState
from paper_reviewer.rubrics import calculate_weighted_score, score_to_decision
from paper_reviewer.graph import build_review_graph
from paper_reviewer.graph import build_rebuttal_graph, _route_rebuttal


class TestRubrics:
    def test_weighted_score_calculation(self):
        scores = {
            "originality": 80,
            "methodology": 70,
            "evidence": 75,
            "coherence": 85,
            "writing": 80,
        }
        result = calculate_weighted_score(scores)
        expected = 80 * 0.20 + 70 * 0.25 + 75 * 0.25 + 85 * 0.15 + 80 * 0.15
        assert result == round(expected, 1)

    def test_score_to_decision_accept(self):
        assert score_to_decision(85) == "Accept"

    def test_score_to_decision_minor(self):
        assert score_to_decision(70) == "Minor Revision"

    def test_score_to_decision_major(self):
        assert score_to_decision(55) == "Major Revision"

    def test_score_to_decision_reject(self):
        assert score_to_decision(40) == "Reject"


class TestState:
    def test_initial_state(self):
        state = ReviewState(
            paper="test",
            paper_title="test",
            language="zh",
            primary_discipline="",
            secondary_disciplines=[],
            research_paradigm="",
            methodology_type="",
            target_journal_tier="",
            reviewer_configs=[],
            eic_report=None,
            methodology_report=None,
            domain_report=None,
            perspective_report=None,
            devils_advocate_report=None,
            editorial_decision="",
            consensus_analysis=None,
            dimension_scores=None,
            revision_roadmap=None,
        )
        assert state["paper"] == "test"
        assert state["eic_report"] is None


class TestGraph:
    def test_graph_builds(self):
        """验证图能正确编译。"""
        app = build_review_graph()
        assert app is not None

    def test_graph_runs_end_to_end(self):
        """端到端测试：用一篇短论文运行完整审稿流程。"""
        app = build_review_graph()
        # 使用一篇极简论文（实际测试时替换为真实短论文）
        short_paper = """
        摘要：本研究探讨了人工智能在教育领域的应用。
        方法：采用问卷调查法，收集了200名学生的数据。
        结果：发现AI工具能显著提升学习效率。
        结论：建议在教学中推广AI工具。
        """
        initial_state = ReviewState(
            paper=short_paper,
            paper_title="AI教育应用测试论文",
            language="zh",
            primary_discipline="",
            secondary_disciplines=[],
            research_paradigm="",
            methodology_type="",
            target_journal_tier="",
            reviewer_configs=[],
            eic_report=None,
            methodology_report=None,
            domain_report=None,
            perspective_report=None,
            devils_advocate_report=None,
            editorial_decision="",
            consensus_analysis=None,
            dimension_scores=None,
            revision_roadmap=None,
        )
        result = app.invoke(initial_state)
        assert result["editorial_decision"] in ["Accept", "Minor Revision", "Major Revision", "Reject"]
        assert result["eic_report"] is not None
        assert result["devils_advocate_report"] is not None
        assert result["dimension_scores"] is not None


class TestRebuttalGraph:
    def test_rebuttal_graph_compiles(self):
        app = build_rebuttal_graph()
        assert app is not None

    def test_route_all_reviewers(self):
        out = _route_rebuttal({"rebuttal_target": "all"})
        assert set(out) == {"eic", "methodology", "domain", "perspective", "devils_advocate"}

    def test_route_single_reviewer(self):
        out = _route_rebuttal({"rebuttal_target": "eic"})
        assert out == ["eic"]

    def test_route_unknown_target_defaults_to_all(self):
        out = _route_rebuttal({"rebuttal_target": "nonsense"})
        assert set(out) == {"eic", "methodology", "domain", "perspective", "devils_advocate"}

    def test_route_missing_target_defaults_to_all(self):
        out = _route_rebuttal({})
        assert set(out) == {"eic", "methodology", "domain", "perspective", "devils_advocate"}
