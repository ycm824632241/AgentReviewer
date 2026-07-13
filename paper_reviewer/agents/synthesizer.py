"""
Synthesizer v2: 拆分为两次 LLM 调用，避免单次输出过大导致截断。

调用 1 - 编辑决定: 综合 5 份报告 → editorial_decision + final_scores + consensus
调用 2 - 修订路线图: 根据决定 + 全部弱点 → revision_roadmap
"""
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import SYNTHESIZER_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
from paper_reviewer.rubrics import DIMENSIONS, calculate_weighted_score, score_to_decision
import json


SYNTHESIZER_DECISION_SCHEMA = """
输出为 JSON 格式（精简版，仅包含决定和分数）:
{{
  "editorial_decision": "Accept / Minor Revision / Major Revision / Reject",
  "decision_rationale": "200字以内决定依据",
  "final_scores": {{
    "originality": 78,
    "methodology": 65,
    "evidence": 72,
    "coherence": 80,
    "writing": 75,
    "weighted_total": 73.2
  }},
  "consensus_summary": "一句话概括共识",
  "devils_advocate_handling": "DA的CRITICAL问题编辑如何处理"
}}
"""


SYNTHESIZER_ROADMAP_SCHEMA = """
输出为 JSON 格式:
{{
  "revision_roadmap": {{
    "integrated_paper_issues": [
      {{"issue": "论文需要修改的问题", "why_it_matters": "为什么影响录用判断", "revision_direction": "整合后的修改方向"}}
    ],
    "priority_1_structural": [
      {{"item": "具体修订建议", "effort": "3天"}}
    ],
    "priority_2_content": [
      {{"item": "具体修订建议", "effort": "2天"}}
    ],
    "priority_3_formatting": [
      {{"item": "具体修订建议", "effort": "1天"}}
    ]
  }}
}}

要求:
- integrated_paper_issues 是编辑整合后的“论文需要修改的问题”，不要逐个审稿人罗列，3-6 项
- P1 必须修改（影响核心结论的方法论或逻辑问题），3-5 项
- P2 应当修改（补充内容但不改变结论），2-4 项
- P3 建议修改（语言和格式问题），1-3 项
- P1/P2/P3 每项附带 effort（预计工时），不需要逐条展示来源审稿人
"""


def _summarize_report(report: dict) -> dict:
    """提取审稿人报告的精简版。"""
    weaknesses = []
    for w in report.get("weaknesses", []):
        if isinstance(w, dict):
            weaknesses.append(w.get("title", "") + " [" + w.get("severity", "") + "]")
        elif isinstance(w, str):
            weaknesses.append(w)
    return {
        "role": report.get("reviewer_role", ""),
        "recommendation": report.get("recommendation", ""),
        "confidence": report.get("confidence", ""),
        "weighted_average": report.get("weighted_average", ""),
        "dimension_scores": report.get("dimension_scores", {}),
        "weaknesses": weaknesses,
    }


def _extract_json_safe(content: str) -> dict:
    """安全解析 JSON（自动处理截断和控制字符）。"""
    try:
        return _safe_json_loads(_extract_json(content))
    except (json.JSONDecodeError, ValueError, KeyError):
        raise


def synthesizer_node(state: ReviewState) -> ReviewState:
    """
    Synthesizer v2: 两次独立 LLM 调用，避免截断。
    """
    llm = get_llm(max_tokens=4096)

    # === 调用 1: 编辑决定 + 分数 ===
    decision_prompt = ChatPromptTemplate.from_messages([
        ("system", SYNTHESIZER_SYSTEM + "\n\n" + SYNTHESIZER_DECISION_SCHEMA),
        ("human", """请综合以下审稿报告，做出编辑决定。

EIC 报告: {eic}

方法论审稿人报告: {methodology}

领域专家报告: {domain}

跨学科视角报告: {perspective}

魔鬼代言人报告: {da}

铁律: 如果 DA 有 CRITICAL 问题，editorial_decision 不能是 Accept。"""),
    ])

    decision_inputs = {
        "eic": json.dumps(_summarize_report(state["eic_report"]), ensure_ascii=False, indent=2),
        "methodology": json.dumps(_summarize_report(state["methodology_report"]), ensure_ascii=False, indent=2),
        "domain": json.dumps(_summarize_report(state["domain_report"]), ensure_ascii=False, indent=2),
        "perspective": json.dumps(_summarize_report(state["perspective_report"]), ensure_ascii=False, indent=2),
        "da": json.dumps(state["devils_advocate_report"], ensure_ascii=False, indent=2),
    }

    # 调用 1 带重试
    decision_result = None
    for attempt in range(3):
        try:
            result = llm.invoke(decision_prompt.format(**decision_inputs))
            decision_result = _extract_json_safe(result.content)
            break
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    if decision_result is None:
        # 全部失败，兜底
        decision_result = {
            "editorial_decision": "Major Revision",
            "decision_rationale": "无法综合，建议大修",
            "final_scores": {"originality": 50, "methodology": 50, "evidence": 50,
                             "coherence": 50, "writing": 50, "weighted_total": 50},
            "consensus_summary": "综合失败",
            "devils_advocate_handling": "未知",
        }

    # === 调用 2: 修订路线图 ===
    # 提取所有弱点作为路线图输入
    all_weaknesses = []
    for role_key in ["eic_report", "methodology_report", "domain_report", "perspective_report"]:
        report = state.get(role_key, {})
        role = report.get("reviewer_role", role_key)
        for w in report.get("weaknesses", []):
            if isinstance(w, dict):
                all_weaknesses.append(f"[{role}] {w.get('title', '')} ({w.get('severity', '')})")
            elif isinstance(w, str):
                all_weaknesses.append(f"[{role}] {w}")

    # DA 的 CRITICAL
    da_issues = state.get("devils_advocate_report", {}).get("CRITICAL", [])
    for issue in da_issues:
        all_weaknesses.append(f"[DA-CRITICAL] {issue.get('description', issue)}")

    roadmap_prompt = ChatPromptTemplate.from_messages([
        ("system", SYNTHESIZER_ROADMAP_SCHEMA),
        ("human", """请根据以下编辑决定和审查问题清单，制定修订路线图。

编辑决定: {decision}

审查问题清单:
{weaknesses}

要求: 先整合分析，输出 integrated_paper_issues 作为论文层面的核心修改问题；不要逐个审稿人罗列。P1 回应 DA 的 CRITICAL 问题和核心方法论缺陷，P2 补充内容，P3 格式语言。"""),
    ])

    roadmap_inputs = {
        "decision": decision_result["editorial_decision"],
        "weaknesses": "\n".join(f"  - {w}" for w in all_weaknesses),
    }

    # 调用 2 带重试
    roadmap_result = None
    for attempt in range(3):
        try:
            result = llm.invoke(roadmap_prompt.format(**roadmap_inputs))
            roadmap_result = _extract_json_safe(result.content)
            break
        except (json.JSONDecodeError, ValueError, KeyError):
            continue

    if roadmap_result is None:
        roadmap_result = {"revision_roadmap": {}}

    return {
        "editorial_decision": decision_result["editorial_decision"],
        "consensus_analysis": {
            "summary": decision_result.get("consensus_summary", ""),
            "devils_advocate_handling": decision_result.get("devils_advocate_handling", ""),
        },
        "revision_roadmap": roadmap_result.get("revision_roadmap", {}),
        "dimension_scores": decision_result.get("final_scores", {}),
        "synthesized_round": state.get("round_number", 1),
    }
