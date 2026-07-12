import re
import json
import os
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI


def _extract_json(text: str) -> str:
    """从 LLM 输出中提取 JSON 块（容错版：处理截断和控制字符）。"""
    # 尝试提取 markdown 代码块
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        return match.group(1).strip()

    # 优先用标准 JSONDecoder 从每个候选起点解析完整对象。
    # 这能正确处理 new_report 这类多层嵌套 JSON，避免正则误取内层对象。
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", text):
        start = match.start()
        try:
            _, end = decoder.raw_decode(text[start:])
            return text[start:start + end]
        except json.JSONDecodeError:
            continue

    # 回退：贪婪匹配 + 截断修复
    match = re.search(r"\{.*", text, re.DOTALL)
    if match:
        json_str = match.group(0)
        return _fix_truncated_json(json_str)

    raise ValueError(f"无法从输出中提取 JSON: {text[:200]}")


def _safe_json_loads(json_str: str) -> dict:
    """安全解析 JSON：处理 MiMo 返回的控制字符问题。"""
    # 1. 标准解析
    try:
        return json.loads(json_str)
    except json.JSONDecodeError:
        pass

    # 2. 移除控制字符后重试
    cleaned = re.sub(r'[\x00-\x1f\x7f]', ' ', json_str)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # 3. strict=False 模式（允许控制字符）
    try:
        return json.loads(json_str, strict=False)
    except json.JSONDecodeError:
        pass

    raise ValueError(f"JSON 解析失败: {json_str[:200]}")


def _fix_truncated_json(json_str: str) -> str:
    """修复被截断的 JSON：在关键分隔点截断并补全括号。"""
    json_str = json_str.rstrip()

    # 如果已经能解析，直接返回
    try:
        json.loads(json_str)
        return json_str
    except json.JSONDecodeError:
        pass

    # 从字符串末尾开始，在引号+逗号/括号位置截断
    # 找最后一个完整的 "..." , 或 "..." } 或 "..." ]
    for i in range(len(json_str) - 1, 0, -1):
        if json_str[i] in ',}]':
            # 检查前面是否是合法值结尾（引号、数字、true/false/null）
            prefix = json_str[:i + 1].rstrip()
            if prefix and prefix[-1] in '}"012345678elt]':
                candidate = prefix
                # 补全顶层括号
                open_braces = candidate.count("{") - candidate.count("}")
                open_brackets = candidate.count("[") - candidate.count("]")
                candidate += "]" * max(0, open_brackets)
                candidate += "}" * max(0, open_braces)
                try:
                    json.loads(candidate)
                    return candidate
                except json.JSONDecodeError:
                    continue

    # 最终兜底
    open_braces = json_str.count("{") - json_str.count("}")
    open_brackets = json_str.count("[") - json_str.count("]")
    json_str += "]" * max(0, open_brackets)
    json_str += "}" * max(0, open_braces)
    return json_str


def normalize_scores(dimension_scores: dict) -> dict:
    """
    标准化维度分数。
    LLM 有时返回 0-10 而非 0-100，自动检测并映射到 0-100。
    """
    normalized = {}
    for dim, score in dimension_scores.items():
        val = float(score)
        # 如果所有分数都 <= 10，认为是 0-10 标度，映射到 0-100
        if val <= 10:
            val = val * 10
        normalized[dim] = min(100, max(0, val))
    return normalized


def normalize_recommendation(text: str) -> str:
    """
    标准化推荐决定文本。
    将各种变体映射到 4 个标准选项。
    """
    text_lower = text.lower().strip()

    # Accept 类
    if any(kw in text_lower for kw in ["accept", "accept with minor", "minor revision", "小修", "接受", "直接接受"]):
        if any(kw in text_lower for kw in ["minor", "小修", "with minor"]):
            return "Minor Revision"
        return "Accept"

    # Reject 类
    if any(kw in text_lower for kw in ["reject", "拒稿", "拒绝", "reject (revise"]):
        # Reject (Revise and Resubmit) → Major Revision
        if any(kw in text_lower for kw in ["revise", "resubmit", "修改后重投"]):
            return "Major Revision"
        return "Reject"

    # Major Revision 类
    if any(kw in text_lower for kw in ["major", "大修", "重大修改", "substantial"]):
        return "Major Revision"

    # Default
    return "Major Revision"


def normalize_report(report: dict) -> dict:
    """
    标准化审稿人报告：分数标度 + 推荐决定。
    在各 reviewer agent 返回前调用。"""
    # 标准化分数
    if "dimension_scores" in report:
        report["dimension_scores"] = normalize_scores(report["dimension_scores"])
        # 重新计算加权平均
        weights = {
            "originality": 0.20, "methodology": 0.25,
            "evidence": 0.25, "coherence": 0.15, "writing": 0.15
        }
        report["weighted_average"] = round(
            sum(report["dimension_scores"].get(d, 0) * w for d, w in weights.items()), 1
        )

    # 标准化推荐决定
    if "recommendation" in report:
        report["recommendation"] = normalize_recommendation(report["recommendation"])

    return report


def with_retry(node_fn, max_retries: int = 2):
    """
    reviewer 节点重试包装器。
    当 JSON 解析失败时自动重试 LLM 调用。
    """
    def wrapper(state, rag_index=None):
        last_error = None
        for _ in range(max_retries + 1):
            try:
                return node_fn(state, rag_index) if rag_index is not None else node_fn(state)
            except (json.JSONDecodeError, ValueError, KeyError, TypeError) as e:
                last_error = e
                continue
        # 全部重试失败
        raise RuntimeError(f"Node failed after {max_retries + 1} attempts: {last_error}")
    return wrapper


def get_llm(temperature=0.3, max_tokens=4096):
    env_path = os.path.join(os.path.dirname(__file__), "..", "20-multi-agent-debate", ".env")
    load_dotenv(dotenv_path=env_path)
    return ChatOpenAI(
        model=os.getenv("MIMO_MODEL_DEBATER", "mimo-v2.5-pro"),
        api_key=os.getenv("MIMO_API_KEY"),
        base_url=os.getenv("MIMO_BASE_URL", "https://token-plan-cn.xiaomimimo.com/v1"),
        temperature=temperature,
        max_tokens=max_tokens,
    )
