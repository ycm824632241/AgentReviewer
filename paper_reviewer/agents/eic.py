from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import EIC_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
import json

EIC_OUTPUT_SCHEMA = """
输出为 JSON 格式：
{{
  "recommendation": "Accept / Minor Revision / Major Revision / Reject",
  "confidence": 3,
  "dimension_scores": {{
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75
  }},
  "strengths": [{{"title": "...", "description": "...", "citation": "p. X"}}],
  "weaknesses": [{{"title": "...", "problem": "...", "why_it_matters": "...", "suggestion": "...", "severity": "Major"}}],
  "questions_for_author": ["..."]
}}
"""

def eic_node(state: ReviewState, rag_index=None) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][0]
    # RAG：如果有索引则检索相关段落，否则用全文
    if rag_index is not None:
        paper_text = rag_index.retrieve("research originality significance overall quality contribution")
    else:
        paper_text = state["paper"]
    prompt = ChatPromptTemplate.from_messages([
        ("system", EIC_SYSTEM + "\n\n" + EIC_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"] + "，专长：" + config["expertise"],
        essay=paper_text
    ))
    report = _safe_json_loads(_extract_json(result.content))
    report["reviewer_role"] = "EIC"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    # 标准化分数和推荐决定
    report = normalize_report(report)
    return {"eic_report": report}
