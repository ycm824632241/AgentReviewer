"""Tests for rebuttal_reviewer.py — Task 4: Rebuttal 专用审稿人节点。"""
import pytest
from paper_reviewer.agents.rebuttal_reviewer import build_rebuttal_report_node


class TestRebuttalReviewer:
    def test_factory_returns_callable(self):
        """工厂对每个合法 role 都应返回可调用的节点函数。"""
        for role in ("eic", "methodology", "domain", "perspective", "devils_advocate"):
            fn = build_rebuttal_report_node(role)
            assert callable(fn), f"role={role} 未返回 callable"

    def test_node_requires_round_two(self):
        """round_number < 2 时 rebuttal 节点应拒绝执行。"""
        fn = build_rebuttal_report_node("eic")
        with pytest.raises(RuntimeError):
            fn({"round_number": 1, "rebuttal_text": "xxx", "eic_report": {}})

    def test_node_requires_previous_report(self):
        """缺少上一轮报告时应拒绝执行。"""
        fn = build_rebuttal_report_node("eic")
        with pytest.raises(RuntimeError):
            fn({"round_number": 2, "rebuttal_text": "xxx", "eic_report": None})

    def test_node_fn_name_is_role_specific(self):
        """节点函数的 __name__ 应体现 role，便于 LangGraph 路由。"""
        fn = build_rebuttal_report_node("methodology")
        assert fn.__name__ == "rebuttal_methodology"
