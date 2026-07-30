from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import DOMAIN_REVIEWER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
import json

DOMAIN_OUTPUT_SCHEMA = """
输出为 JSON 格式（与其他审稿人相同的结构，额外包含 literature_integration 维度分数）：
{{
  "recommendation": "...",
  "confidence": 4,
  "dimension_scores": {{"originality": ..., "methodology": ..., "evidence": ..., "coherence": ..., "writing": ...}},
  "literature_integration": 75,
  "strengths": [...],
  "weaknesses": [...],
  "questions_for_author": [...]
}}
注意：你的焦点是文献覆盖、理论框架和领域贡献。
"""

def domain_reviewer_node(state: ReviewState, rag_index=None) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][2]
    # RAG：检索文献综述和理论框架相关段落
    if rag_index is not None:
        paper_text = rag_index.retrieve("literature review theoretical framework domain contribution related work")
    else:
        paper_text = state["paper"]
    prompt = ChatPromptTemplate.from_messages([
        ("system", DOMAIN_REVIEWER_SYSTEM + "\n\n" + DOMAIN_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请从领域专家角度审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"],
        essay=paper_text
    ))
    report = _safe_json_loads(_extract_json(result.content))
    report["reviewer_role"] = "领域评审人"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    # 标准化分数和推荐决定
    report = normalize_report(report)
    return {"domain_report": report}
