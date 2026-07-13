from paper_reviewer.agents import synthesizer
from paper_reviewer.prompts.system_prompts import SYNTHESIZER_SYSTEM


def test_synthesizer_prompt_requires_integrated_revision_issues():
    assert "整合分析" in SYNTHESIZER_SYSTEM
    assert "不要逐个审稿人罗列" in SYNTHESIZER_SYSTEM
    assert "论文需要修改的问题" in SYNTHESIZER_SYSTEM


def test_roadmap_schema_names_integrated_paper_issues():
    assert "integrated_paper_issues" in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
    assert "论文需要修改的问题" in synthesizer.SYNTHESIZER_ROADMAP_SCHEMA
