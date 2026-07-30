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


_DECISION_SEVERITY = {
    "Accept": 0,
    "Minor Revision": 1,
    "Major Revision": 2,
    "Reject": 3,
}


_REVIEWER_TRACE_ROLES = [
    ("eic_report", "主编视角评审人"),
    ("methodology_report", "方法论评审人"),
    ("domain_report", "领域评审人"),
    ("perspective_report", "跨学科评审人"),
]

_DECISION_LABELS = {
    "Accept": "接收",
    "Minor Revision": "小修",
    "Major Revision": "大修",
    "Reject": "拒稿",
}


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
  "devils_advocate_handling": "魔鬼评审人提出的关键风险如何作为修订线索处理"
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
      {{"issue": "必须修改的问题", "revision_direction": "具体修订方向"}}
    ],
    "priority_2_content": [
      {{"issue": "应当修改的问题", "revision_direction": "具体修订方向"}}
    ],
    "priority_3_formatting": [
      {{"issue": "建议修改的问题", "revision_direction": "具体修订方向"}}
    ]
  }}
}}

要求:
- integrated_paper_issues 是编辑整合后的“论文需要修改的问题”，不要逐个审稿人罗列，3-6 项
- P1 必须修改（影响核心结论的方法论或逻辑问题），3-5 项
- P2 应当修改（补充内容但不改变结论），2-4 项
- P3 建议修改（语言和格式问题），1-3 项
- P1/P2/P3 只输出问题和修改方向，不输出时间估计或来源审稿人
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


def _normalize_decision(value: object) -> str:
    """Normalize common English/Chinese recommendation labels."""
    text = str(value or "").strip().lower()
    if not text:
        return ""
    if "reject" in text or "拒" in text:
        return "Reject"
    if "major" in text or "大修" in text:
        return "Major Revision"
    if "minor" in text or "小修" in text:
        return "Minor Revision"
    if "accept" in text or "接收" in text or "录用" in text:
        return "Accept"
    return ""


def _get_da_critical_issues(da_report: dict) -> list:
    """Support both top-level CRITICAL and issues.CRITICAL DA report shapes."""
    critical = []
    top_level = da_report.get("CRITICAL", [])
    nested = da_report.get("issues", {}).get("CRITICAL", []) if isinstance(da_report.get("issues"), dict) else []
    for value in (top_level, nested):
        if isinstance(value, list):
            critical.extend(value)
        elif value:
            critical.append(value)
    return critical


def _reviewer_recommendations(state: ReviewState) -> list[str]:
    recommendations = []
    for role_key, _ in _REVIEWER_TRACE_ROLES:
        report = state.get(role_key, {})
        if not isinstance(report, dict):
            continue
        normalized = _normalize_decision(report.get("recommendation") or report.get("decision"))
        if normalized:
            recommendations.append(normalized)
    return recommendations


def _coerce_score(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return round(float(value), 1)
    except (TypeError, ValueError):
        return None


def _reviewer_trace_values(state: ReviewState) -> tuple[dict[str, str], dict[str, float]]:
    recommendations = {}
    weighted_scores = {}
    for role_key, label in _REVIEWER_TRACE_ROLES:
        report = state.get(role_key, {})
        if not isinstance(report, dict):
            continue

        normalized = _normalize_decision(report.get("recommendation") or report.get("decision"))
        if normalized:
            recommendations[label] = normalized

        score = _coerce_score(report.get("weighted_average"))
        if score is not None:
            weighted_scores[label] = score

    return recommendations, weighted_scores


def _recommendation_distribution(recommendations: dict[str, str]) -> str:
    if not recommendations:
        return "普通评审人暂无结构化推荐"

    parts = []
    for decision in ["Accept", "Minor Revision", "Major Revision", "Reject"]:
        count = sum(1 for value in recommendations.values() if value == decision)
        if count:
            parts.append(f"{count} 位建议{_DECISION_LABELS.get(decision, decision)}")
    return "普通评审推荐：" + "，".join(parts)


def _build_decision_trace(
    decision_result: dict,
    state: ReviewState,
    applied_rules: list[str],
    original_decision: str,
) -> dict:
    recommendations, weighted_scores = _reviewer_trace_values(state)
    critical_count = len(_get_da_critical_issues(state.get("devils_advocate_report", {}) or {}))
    final_decision = _normalize_decision(decision_result.get("editorial_decision")) or str(
        decision_result.get("editorial_decision", "")
    ).strip()

    if not applied_rules:
        applied_rules = ["未触发硬性校准规则。"]

    decision_summary = (
        f"{_recommendation_distribution(recommendations)}；"
        f"魔鬼评审人关键风险：{critical_count} 个（仅作风险提示）；"
        f"综合编辑决定：{_DECISION_LABELS.get(final_decision, final_decision) or '暂无'}。"
    )

    return {
        "original_decision": original_decision,
        "final_decision": final_decision,
        "decision_rationale": decision_result.get("decision_rationale", ""),
        "decision_summary": decision_summary,
        "reviewer_recommendations": recommendations,
        "reviewer_weighted_scores": weighted_scores,
        "da_critical_count": critical_count,
        "applied_rules": applied_rules,
    }


def _append_rationale(decision_result: dict, note: str) -> None:
    rationale = str(decision_result.get("decision_rationale", "")).strip()
    decision_result["decision_rationale"] = f"{rationale} {note}".strip()


def _align_decision_with_reviewer_consensus(decision_result: dict, state: ReviewState) -> dict:
    """Keep the editor decision consistent with ordinary reviewer consensus."""
    aligned = dict(decision_result)
    decision = _normalize_decision(aligned.get("editorial_decision")) or "Major Revision"
    original_decision = decision
    applied_rules = ["魔鬼评审人仅作为压力测试和风险提示，不参与最终评分或录用决定。"]
    recommendations = _reviewer_recommendations(state)

    if recommendations:
        all_accept_or_minor = all(_DECISION_SEVERITY[rec] <= _DECISION_SEVERITY["Minor Revision"] for rec in recommendations)
        too_severe = _DECISION_SEVERITY[decision] > _DECISION_SEVERITY["Minor Revision"]
        if all_accept_or_minor and too_severe:
            decision = "Minor Revision"
            _append_rationale(aligned, "多数普通评审建议为接收或小修，因此综合编辑决定校准为小修。")
            applied_rules.append("普通评审共识规则：多数建议为接收或小修，原决定过严，已校准为小修。")
        else:
            applied_rules.append("普通评审意见已纳入综合编辑判断，未触发过度严厉校准。")

    aligned["editorial_decision"] = decision
    aligned["decision_trace"] = _build_decision_trace(aligned, state, applied_rules, original_decision)
    return aligned


def synthesizer_node(state: ReviewState) -> ReviewState:
    """
    Synthesizer v2: 两次独立 LLM 调用，避免截断。
    """
    llm = get_llm(max_tokens=4096)

    # === 调用 1: 编辑决定 + 分数 ===
    decision_prompt = ChatPromptTemplate.from_messages([
        ("system", SYNTHESIZER_SYSTEM + "\n\n" + SYNTHESIZER_DECISION_SCHEMA),
        ("human", """请综合以下审稿报告，做出编辑决定。

主编视角评审人报告: {eic}

方法论审稿人报告: {methodology}

领域专家报告: {domain}

跨学科视角报告: {perspective}

魔鬼评审人报告: {da}

说明: 魔鬼评审人报告仅作为压力测试和风险提示，不参与普通评审推荐统计，也不能作为否决或降级最终决定的硬规则。"""),
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
    decision_result = _align_decision_with_reviewer_consensus(decision_result, state)

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

    # 魔鬼评审人的关键风险仅进入修订路线图，不参与最终决定校准。
    da_issues = _get_da_critical_issues(state.get("devils_advocate_report", {}) or {})
    for issue in da_issues:
        all_weaknesses.append(f"[魔鬼评审人关键风险] {issue.get('description', issue)}")

    roadmap_prompt = ChatPromptTemplate.from_messages([
        ("system", SYNTHESIZER_ROADMAP_SCHEMA),
        ("human", """请根据以下编辑决定和审查问题清单，制定修订路线图。

编辑决定: {decision}

审查问题清单:
{weaknesses}

要求: 先整合分析，输出 integrated_paper_issues 作为论文层面的核心修改问题；不要逐个审稿人罗列。P1 回应核心方法论缺陷和魔鬼评审人提出的关键风险，P2 补充内容，P3 格式语言。"""),
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
        "decision_trace": decision_result.get("decision_trace", {}),
        "synthesized_round": state.get("round_number", 1),
    }
