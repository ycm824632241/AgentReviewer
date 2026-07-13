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
    assert "多数审稿建议" in aligned["decision_rationale"]


def test_da_critical_prevents_accept_decision():
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

    assert aligned["editorial_decision"] == "Minor Revision"
    assert "DA CRITICAL" in aligned["decision_rationale"]
