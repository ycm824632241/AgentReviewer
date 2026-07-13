from paper_reviewer.prompts import system_prompts
from paper_reviewer.rag.retriever import _chunk_text


def test_reviewer_system_prompts_require_chinese_output():
    prompt_names = [
        "FIELD_ANALYST_SYSTEM",
        "EIC_SYSTEM",
        "METHODOLOGY_REVIEWER_SYSTEM",
        "DOMAIN_REVIEWER_SYSTEM",
        "PERSPECTIVE_REVIEWER_SYSTEM",
        "DEVILS_ADVOCATE_SYSTEM",
        "SYNTHESIZER_SYSTEM",
    ]

    for name in prompt_names:
        prompt = getattr(system_prompts, name)
        assert "必须使用中文输出" in prompt


def test_chunk_text_splits_single_oversized_paragraph():
    text = "A" * 2400

    chunks = _chunk_text(text, size=500, overlap=50)

    assert len(chunks) > 1
    assert max(len(chunk) for chunk in chunks) <= 550
