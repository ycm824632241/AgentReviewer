from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import METHODOLOGY_REVIEWER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
import json

METHODOLOGY_OUTPUT_SCHEMA = """
输出为 JSON 格式（与主编视角评审人相同的结构）：
{{
  "recommendation": "...",
  "confidence": 4,
  "dimension_scores": {{"originality": ..., "methodology": ..., "evidence": ..., "coherence": ..., "writing": ...}},
  "strengths": [...],
  "weaknesses": [...],
  "questions_for_author": [...]
}}
注意：你的焦点是方法论严谨性，所有优缺点必须引用论文具体段落。
"""

def methodology_reviewer_node(state: ReviewState, rag_index=None) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][1]
    # RAG：检索方法论相关段落
    if rag_index is not None:
        paper_text = rag_index.retrieve("research design methodology methods statistical analysis data collection sampling")
    else:
        paper_text = state["paper"]
    prompt = ChatPromptTemplate.from_messages([
        ("system", METHODOLOGY_REVIEWER_SYSTEM + "\n\n" + METHODOLOGY_OUTPUT_SCHEMA),
        ("human", "你是 {identity}。请从方法论角度审阅以下论文：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(
        identity=config["identity"],
        essay=paper_text
    ))
    report = _safe_json_loads(_extract_json(result.content))
    report["reviewer_role"] = "方法论评审人"
    report["weighted_average"] = sum(
        report["dimension_scores"][d] * w
        for d, w in [("originality", 0.20), ("methodology", 0.25),
                      ("evidence", 0.25), ("coherence", 0.15), ("writing", 0.15)]
    )
    # 标准化分数和推荐决定
    report = normalize_report(report)
    return {"methodology_report": report}
