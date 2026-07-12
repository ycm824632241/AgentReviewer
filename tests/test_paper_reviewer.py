import pytest
import os
import sys
import json
import tempfile
from unittest.mock import patch

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


# ── Integration tests (mocked LLM, fast) ─────────────────────────────────────
import contextlib
import paper_reviewer.agents.field_analyst as _fa
import paper_reviewer.agents.eic as _eic
import paper_reviewer.agents.methodology_reviewer as _mr
import paper_reviewer.agents.domain_reviewer as _dr
import paper_reviewer.agents.perspective_reviewer as _pr
import paper_reviewer.agents.devils_advocate as _da
import paper_reviewer.agents.synthesizer as _syn
import paper_reviewer.agents.rebuttal_reviewer as _rr


class _Resp:
    def __init__(self, content):
        self.content = content


class _FakeLLM:
    """按 prompt 关键词返回对应 JSON 的伪 LLM（无网络调用，<30s）。"""

    def __init__(self):
        self.calls = []

    def invoke(self, prompt_str):
        t = str(prompt_str)
        self.calls.append(t)
        if "请分析以下论文并生成审稿团队配置卡" in t:
            return _Resp(_FIELD_CONFIG_JSON)
        if "最强压力测试" in t:
            return _Resp(_DA_JSON)
        if "逐点回应" in t or "persuasion_level" in t:
            return _Resp(_REBUTTAL_JSON)
        if "审查问题清单" in t:
            return _Resp(_ROADMAP_JSON)
        if "请综合以下审稿报告" in t:
            return _Resp(_DECISION_JSON)
        return _Resp(_REPORT_JSON)


@contextlib.contextmanager
def _patch_llm():
    fake = _FakeLLM()
    with contextlib.ExitStack() as stack:
        for mod in (_fa, _eic, _mr, _dr, _pr, _da, _syn, _rr):
            stack.enter_context(patch.object(mod, "get_llm", lambda *_a, **_k: fake))
        yield fake


# 各节点期望的 JSON 形态
_FIELD_CONFIG_JSON = json.dumps({
    "primary_discipline": "计算机科学",
    "secondary_disciplines": ["人工智能"],
    "research_paradigm": "定量",
    "methodology_type": "实验研究",
    "target_journal_tier": "Q1",
    "reviewer_configs": [
        {"role": "EIC", "identity": "某期刊主编", "expertise": "学术出版", "focus": "原创性"},
        {"role": "Methodology", "identity": "统计学家", "expertise": "实验设计", "focus": "方法"},
        {"role": "Domain", "identity": "AI研究员", "expertise": "AI教育", "focus": "贡献"},
        {"role": "Perspective", "identity": "跨学科研究员", "expertise": "教育技术", "focus": "影响"},
        {"role": "Devil", "identity": "批判学者", "expertise": "逻辑", "focus": "反证"},
    ],
}, ensure_ascii=False)

_REPORT_JSON = json.dumps({
    "recommendation": "Minor Revision", "confidence": 3,
    "dimension_scores": {"originality": 70, "methodology": 65, "evidence": 72, "coherence": 80, "writing": 75},
    "strengths": [{"title": "清晰的论点", "description": "明确", "citation": "p.1"}],
    "weaknesses": [{"title": "样本量小", "problem": "不足", "why_it_matters": "功效",
                    "suggestion": "扩大", "severity": "MAJOR"}],
    "questions_for_author": ["问题1"],
}, ensure_ascii=False)

_DA_JSON = json.dumps({
    "strongest_counter_argument": "反向论证：技术未必提升学习。",
    "issues": {"CRITICAL": [{"dimension": "核心逻辑", "description": "因果推断不成立", "location": "p.3"}],
               "MAJOR": [], "MINOR": []},
    "ignored_alternatives": ["替代解释A"], "missing_stakeholders": ["从业者"],
    "unexamined_premise": "假设技术必然提升学习",
}, ensure_ascii=False)

_DECISION_JSON = json.dumps({
    "editorial_decision": "Minor Revision", "decision_rationale": "整体可行但需补实验",
    "final_scores": {"originality": 70, "methodology": 65, "evidence": 72, "coherence": 80,
                     "writing": 75, "weighted_total": 72.1},
    "consensus_summary": "多数建议小修", "devils_advocate_handling": "要求回应CRITICAL逻辑问题",
}, ensure_ascii=False)

_ROADMAP_JSON = json.dumps({
    "revision_roadmap": {
        "priority_1_structural": [{"item": "补强因果推断", "source": "DA", "effort": "3天"}],
        "priority_2_content": [{"item": "补充文献", "source": "Domain", "effort": "2天"}],
        "priority_3_formatting": [{"item": "修改格式", "source": "EIC", "effort": "1天"}],
    },
}, ensure_ascii=False)

_REBUTTAL_JSON = json.dumps({
    "persuasion_level": "partially_persuaded",
    "adjustment_reason": "作者就第2点提供了新证据",
    "new_report": json.loads(_REPORT_JSON),
}, ensure_ascii=False)

_MINIMAL_PAPER = "摘要：AI教育应用。方法：问卷200人。结果：提升效率。结论：推广。"


class TestIntegration:
    def test_round1_routes_through_field_analyst(self):
        """I1：Round 1 经 field_analyst 生成 reviewer_configs，证明不再是死节点。"""
        app = build_rebuttal_graph(db_path=_tmp_db())
        state = ReviewState(
            paper=_MINIMAL_PAPER, paper_title="t", language="zh",
            primary_discipline="", secondary_disciplines=[], research_paradigm="",
            methodology_type="", target_journal_tier="", reviewer_configs=[],
            eic_report=None, methodology_report=None, domain_report=None,
            perspective_report=None, devils_advocate_report=None,
            editorial_decision="", consensus_analysis=None, dimension_scores=None,
            revision_roadmap=None, round_number=1, rebuttal_text=None,
            rebuttal_target=None, rebuttal_history=[],
        )
        with _patch_llm():
            result = app.invoke(state, config={"configurable": {"thread_id": "r1-it"}})
        # 只有 field_analyst 产出 reviewer_configs / primary_discipline
        assert len(result["reviewer_configs"]) == 5, "field_analyst 未运行（reviewer_configs 为空）"
        assert result["primary_discipline"] == "计算机科学"
        assert result["eic_report"] is not None
        assert result["devils_advocate_report"] is not None
        assert result["editorial_decision"] in ["Accept", "Minor Revision", "Major Revision", "Reject"]
        assert result["rebuttal_history"] == []

    def test_round2_routes_to_rebuttal_node_not_round1_reviewer(self):
        """C1：Round 2 (rebuttal_target=eic) 必须路由到 rebuttal_eic，而非 Round-1 eic 节点。"""
        app = build_rebuttal_graph(db_path=_tmp_db())
        prev_report = json.loads(_REPORT_JSON)
        prev_report["reviewer_role"] = "EIC"
        state = ReviewState(
            paper=_MINIMAL_PAPER, paper_title="t", language="zh",
            primary_discipline="计算机科学", secondary_disciplines=[], research_paradigm="",
            methodology_type="", target_journal_tier="Q1",
            reviewer_configs=json.loads(_FIELD_CONFIG_JSON)["reviewer_configs"],
            eic_report=prev_report,
            methodology_report=json.loads(_REPORT_JSON),
            domain_report=json.loads(_REPORT_JSON),
            perspective_report=json.loads(_REPORT_JSON),
            devils_advocate_report=json.loads(_DA_JSON),
            editorial_decision="", consensus_analysis=None, dimension_scores=None,
            revision_roadmap=None, round_number=2, rebuttal_text="作者申诉：样本经功率分析。",
            rebuttal_target="eic", rebuttal_history=[],
        )
        with _patch_llm() as fake:
            result = app.invoke(state, config={"configurable": {"thread_id": "r2-it"}})
        # rebuttal_history 仅由 rebuttal_* 节点写入 → 证明走的是 rebuttal_eic 而非 eic
        assert len(result["rebuttal_history"]) == 1, (
            f"rebuttal_history 未生成（len={len(result['rebuttal_history'])}），"
            f"路由可能未达 rebuttal_eic；llm调用数={len(fake.calls)}"
        )
        entry = result["rebuttal_history"][0]
        assert entry["role"] == "eic"
        assert entry["round"] == 2
        assert entry["persuasion"] == "partially_persuaded"
        # 若错误地路由到 Round-1 eic 节点，它会读取 state["reviewer_configs"][0] 但
        # 不会写入 rebuttal_history，且不会校验 round_number → 此处断言即可捕获 C1。
        assert result["eic_report"]["reviewer_role"] == "EIC"


def _tmp_db():
    """每个测试用独立的临时 checkpointer DB，避免互相干扰 + 便于清理。"""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    return path
