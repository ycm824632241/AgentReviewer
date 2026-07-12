"""
rebuttal_reviewer.py：基于上一轮报告 + 作者申诉重新评分的节点。
仅在 round >= 2 时合法（rebuttal 是第二轮以后的事情）。
"""
from typing import Callable
from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report
from paper_reviewer.prompts.system_prompts import (
    EIC_SYSTEM,
    METHODOLOGY_REVIEWER_SYSTEM,
    DOMAIN_REVIEWER_SYSTEM,
    PERSPECTIVE_REVIEWER_SYSTEM,
    DEVILS_ADVOCATE_SYSTEM,
)
import json

# role -> 对应角色的 system prompt（沿用第一轮的 prompt 以保证角色一致性）
ROLE_TO_PROMPT = {
    "eic": EIC_SYSTEM,
    "methodology": METHODOLOGY_REVIEWER_SYSTEM,
    "domain": DOMAIN_REVIEWER_SYSTEM,
    "perspective": PERSPECTIVE_REVIEWER_SYSTEM,
    "devils_advocate": DEVILS_ADVOCATE_SYSTEM,
}
# role -> 该角色在 ReviewState 中的报告 key
ROLE_TO_REPORT_KEY = {
    "eic": "eic_report",
    "methodology": "methodology_report",
    "domain": "domain_report",
    "perspective": "perspective_report",
    "devils_advocate": "devils_advocate_report",
}

# 合法性校验：工厂创建时就确保 role 有效（fail fast）
_VALID_ROLES = set(ROLE_TO_PROMPT.keys())

REBUTTAL_OUTPUT_SCHEMA = """
输出 JSON：
{
  "persuasion_level": "fully_persuaded | partially_persuaded | not_persuaded",
  "adjustment_reason": "基于申诉中的第X点，原评分中的Y问题已被解释清楚...",
  "new_report": { 原审稿报告的完整 schema }
}
"""


def build_rebuttal_report_node(role: str) -> Callable:
    """返回 rebuttal_{role}_node(state, rag_index=None) -> dict。

    工厂创建时即校验 role；节点调用时校验 round_number >= 2 + 上一轮报告存在。
    """
    if role not in _VALID_ROLES:
        raise ValueError(
            f"非法 role={role!r}，合法值为: {sorted(_VALID_ROLES)}"
        )

    system_prompt = ROLE_TO_PROMPT[role]
    report_key = ROLE_TO_REPORT_KEY[role]
    node_name = f"rebuttal_{role}"

    def node_fn(state: dict, rag_index=None) -> dict:  # noqa: ARG001 — rag_index 签名对齐保留
        # 防御 1：rebuttal 节点只在第 2 轮及以后有效
        if state.get("round_number", 1) < 2:
            raise RuntimeError(f"{node_name} 仅在 round >= 2 时调用")

        # 防御 2：上一轮报告必须已生成
        previous = state.get(report_key)
        if not previous:
            raise RuntimeError(f"state['{report_key}'] 缺失，无法进行 rebuttal")

        llm = get_llm()
        prompt = ChatPromptTemplate.from_messages([
            (
                "system",
                system_prompt
                + "\n\n你正在参加第二轮审稿（Rebuttal）。请根据上一轮自己的报告 + 作者的逐点回应，重新评估。\n"
                + REBUTTAL_OUTPUT_SCHEMA,
            ),
            (
                "human",
                "论文内容：\n{paper}\n\n你上一轮的审稿报告：\n{previous}\n\n作者的逐点回应（Rebuttal）：\n{rebuttal}\n\n请输出 JSON。",
            ),
        ])
        result = llm.invoke(
            prompt.format(
                paper=state.get("paper", "")[:2000],
                previous=json.dumps(previous, ensure_ascii=False, indent=2),
                rebuttal=state.get("rebuttal_text", ""),
            )
        )
        data = _safe_json_loads(_extract_json(result.content))

        # 保留 reviewer_role 以追溯；normalize 修正分数标度 + 推荐决定文本
        new_report = data["new_report"]
        new_report["reviewer_role"] = previous.get("reviewer_role", role)
        new_report = normalize_report(new_report)

        return {
            report_key: new_report,
            "rebuttal_history": [
                *state.get("rebuttal_history", []),
                {
                    "round": state["round_number"],
                    "role": role,
                    "persuasion": data.get("persuasion_level"),
                    "adjustment_reason": data.get("adjustment_reason"),
                },
            ],
        }

    node_fn.__name__ = node_name
    return node_fn
