from paper_reviewer.agents import synthesizer
from paper_reviewer.prompts.system_prompts import SYNTHESIZER_SYSTEM


def test_synthesizer_prompt_requires_integrated_revision_issues():
    assert "整合分析" in SYNTHESIZER_SYSTEM
    assert "不要逐个审稿人罗列" in SYNTHESIZER_SYSTEM
    assert "论文需要修改的问题" in SYNTHESIZER_SYSTEM


def test_roadmap_schema_names_integrated_paper_issues():
    assert "integrated_paper_issues" in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
    assert "论文需要修改的问题" in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
    assert '"item"' not in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
    assert '"effort"' not in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
    assert "预计工时" not in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA


def test_editor_decision_is_capped_when_reviewers_only_accept_or_minor():
    decision_result = {
        "editorial_decision": "Major Revision",
        "decision_rationale": "模型给出了过重的决定",
    }
    state = {
        "eic_report": {"recommendation": "Accept"},
        "methodology_report": {"recommendation": "Accept"},
        "domain_report": {"recommendation": "Minor Revision"},
        "perspective_report": {"recommendation": "Accept"},
        "devils_advocate_report": {"issues": {"CRITICAL": []}},
    }

    aligned = synthesizer._align_decision_with_reviewer_consensus(decision_result, state)

    assert aligned["editorial_decision"] == "Minor Revision"
    assert "多数普通评审建议" in aligned["decision_rationale"]
    trace = aligned["decision_trace"]
    assert trace["original_decision"] == "Major Revision"
    assert trace["final_decision"] == "Minor Revision"
    assert trace["da_critical_count"] == 0
    assert trace["reviewer_recommendations"] == {
        "主编视角评审人": "Accept",
        "方法论评审人": "Accept",
        "领域评审人": "Minor Revision",
        "跨学科评审人": "Accept",
    }
    assert any("校准" in rule for rule in trace["applied_rules"])


def test_da_critical_does_not_prevent_accept_decision():
    decision_result = {
        "editorial_decision": "Accept",
        "decision_rationale": "模型给出了接收决定",
    }
    state = {
        "eic_report": {"recommendation": "Accept"},
        "methodology_report": {"recommendation": "Accept"},
        "domain_report": {"recommendation": "Accept"},
        "perspective_report": {"recommendation": "Accept"},
        "devils_advocate_report": {
            "issues": {"CRITICAL": [{"description": "核心因果推断不成立"}]}
        },
    }

    aligned = synthesizer._align_decision_with_reviewer_consensus(decision_result, state)

    assert aligned["editorial_decision"] == "Accept"
    assert "DA CRITICAL" not in aligned["decision_rationale"]
    trace = aligned["decision_trace"]
    assert trace["original_decision"] == "Accept"
    assert trace["final_decision"] == "Accept"
    assert trace["da_critical_count"] == 1
    assert any("魔鬼评审人仅作为压力测试" in rule for rule in trace["applied_rules"])


def test_decision_trace_records_weighted_scores_and_summary():
    decision_result = {
        "editorial_decision": "Minor Revision",
        "decision_rationale": "贡献明确，但证据仍需补强。",
    }
    state = {
        "eic_report": {"recommendation": "Minor Revision", "weighted_average": 72.5},
        "methodology_report": {"recommendation": "Major Revision", "weighted_average": 61.0},
        "domain_report": {"recommendation": "Minor Revision", "weighted_average": 70.0},
        "perspective_report": {"recommendation": "Accept", "weighted_average": 78.0},
        "devils_advocate_report": {"issues": {"CRITICAL": []}},
    }

    aligned = synthesizer._align_decision_with_reviewer_consensus(decision_result, state)
    trace = aligned["decision_trace"]

    assert trace["reviewer_weighted_scores"] == {
        "主编视角评审人": 72.5,
        "方法论评审人": 61.0,
        "领域评审人": 70.0,
        "跨学科评审人": 78.0,
    }
    assert "普通评审" in trace["decision_summary"]
    assert "魔鬼评审人" in trace["decision_summary"]
    assert trace["decision_rationale"] == "贡献明确，但证据仍需补强。"
