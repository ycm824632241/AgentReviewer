from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import DEVILS_ADVOCATE_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
import json

DA_OUTPUT_SCHEMA = """
输出为 JSON 格式（注意：你不打分，只挑战）：
{{
  "strongest_counter_argument": "200-300字。如果你是持相反观点的学者，你会如何反驳这篇论文？",
  "issues": {{
    "CRITICAL": [{{"dimension": "核心论点/逻辑链/...", "description": "...", "location": "p. X"}}],
    "MAJOR": [...],
    "MINOR": [...]
  }},
  "ignored_alternatives": ["被忽略的替代解释A", "..."],
  "missing_stakeholders": ["缺失的利益相关者视角1", "..."],
  "unexamined_premise": "论文未明说的前提假设（如有）"
}}
"""

def devils_advocate_node(state: ReviewState, rag_index=None) -> ReviewState:
    llm = get_llm()
    config = state["reviewer_configs"][4]
    # RAG：检索涉及核心论点、因果推断、逻辑链的段落
    if rag_index is not None:
        paper_text = rag_index.retrieve("core argument logical gaps assumptions causal claims limitations confounding factors")
    else:
        paper_text = state["paper"]
    prompt = ChatPromptTemplate.from_messages([
        ("system", DEVILS_ADVOCATE_SYSTEM + "\n\n" + DA_OUTPUT_SCHEMA),
        ("human", "请对以下论文进行最强压力测试：\n\n{essay}"),
    ])
    result = llm.invoke(prompt.format(essay=paper_text))
    report = _safe_json_loads(_extract_json(result.content))
    report["reviewer_role"] = "Devil's Advocate"
    report = normalize_report(report)
    return {"devils_advocate_report": report}
