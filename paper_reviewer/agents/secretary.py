"""
Secretary Agent: 将结构化审稿结果整合为人类可读的 Markdown 报告。

输出格式：标准学术论文审稿报告，包含：
- 论文信息
- 审稿团队
- 各审稿人报告（分数 + 优缺点）
- 魔鬼代言人挑战
- 编辑综合决定
- 修订路线图
"""
from typing import Optional


def generate_report(result: dict, output_path: Optional[str] = None) -> str:
    """
    将审稿结果字典转换为 Markdown 格式报告。

    Args:
        result: review_paper() 返回的结果字典
        output_path: 可选，保存 Markdown 文件路径

    Returns:
        Markdown 格式的报告文本
    """
    lines = []

    # === 标题 ===
    lines.append(f"# 学术论文审稿报告")
    lines.append("")
    lines.append(f"**论文标题**: {result.get('paper_title', 'N/A')}")
    lines.append(f"**论文长度**: {len(result.get('paper', ''))} 字符")
    lines.append("")

    # === 1. 审稿团队 ===
    if result.get("reviewer_configs"):
        lines.append("## 1. 审稿团队配置")
        lines.append("")
        for i, cfg in enumerate(result["reviewer_configs"], 1):
            lines.append(f"**{i}. {cfg['role']}**")
            lines.append(f"   - 身份: {cfg['identity']}")
            lines.append(f"   - 专长: {cfg['expertise']}")
            lines.append(f"   - 焦点: {cfg['focus']}")
        lines.append("")

    # === 2. 编辑决定（放在最前面便于快速查看） ===
    lines.append("---")
    lines.append("")
    lines.append(f"## 编辑决定: {result.get('editorial_decision', 'N/A')}")
    lines.append("")

    dim_scores = result.get("dimension_scores", {})
    if dim_scores:
        lines.append("### 最终维度分数")
        lines.append("")
        lines.append("| 维度 | 分数 |")
        lines.append("|------|------|")
        weights = {
            "originality": "20%", "methodology": "25%", "evidence": "25%",
            "coherence": "15%", "writing": "15%"
        }
        for dim, score in dim_scores.items():
            if dim == "weighted_total":
                continue
            w = weights.get(dim, "")
            lines.append(f"| {dim} ({w}) | {score} |")
        lines.append(f"| **加权总分** | **{dim_scores.get('weighted_total', 'N/A')}** |")
        lines.append("")

    # === 3. 各审稿人报告 ===
    lines.append("---")
    lines.append("")
    lines.append("## 2. 各审稿人报告")
    lines.append("")

    reviewer_sections = [
        ("eic_report", "EIC (主编)"),
        ("methodology_review", "方法论审稿人"),
        ("domain_report", "领域专家"),
        ("perspective_report", "跨学科视角"),
    ]
    for role_key, label in reviewer_sections:
        report = result.get(role_key)
        if not report:
            # Try alternative key names
            for alt in [role_key, role_key.replace("_report", "_review"), role_key.replace("_review", "_report")]:
                report = result.get(alt)
                if report:
                    break
        if not report:
            continue

        lines.append(f"### {label}")
        lines.append("")
        lines.append(f"- **推荐决定**: {report.get('recommendation', 'N/A')}")
        lines.append(f"- **置信度**: {report.get('confidence', 'N/A')}/5")
        lines.append(f"- **加权平均分**: {report.get('weighted_average', 'N/A')}")
        lines.append("")

        # 维度分数
        if report.get("dimension_scores"):
            lines.append("**维度分数:**")
            for dim, score in report["dimension_scores"].items():
                lines.append(f"  - {dim}: {score}")
            lines.append("")

        # 优点
        if report.get("strengths"):
            lines.append("**优点:**")
            for j, s in enumerate(report["strengths"], 1):
                if isinstance(s, dict):
                    title = s.get("title", "")
                    desc = s.get("description", "")
                    cite = s.get("citation", "")
                    cite_str = f" ({cite})" if cite else ""
                    lines.append(f"  {j}. **{title}**: {desc}{cite_str}")
                elif isinstance(s, str):
                    lines.append(f"  {j}. {s}")
            lines.append("")

        # 缺点
        if report.get("weaknesses"):
            lines.append("**缺点:**")
            for j, w in enumerate(report["weaknesses"], 1):
                if isinstance(w, dict):
                    title = w.get("title", "")
                    severity = w.get("severity", "")
                    problem = w.get("problem", "")
                    suggestion = w.get("suggestion", "")
                    tag = f" [{severity}]" if severity else ""
                    lines.append(f"  {j}. **{title}**{tag}: {problem}")
                    if suggestion:
                        lines.append(f"     - 建议: {suggestion}")
                elif isinstance(w, str):
                    lines.append(f"  {j}. {w}")
            lines.append("")

        # 对作者的问题
        if report.get("questions_for_author"):
            lines.append("**需要作者回答的问题:**")
            for j, q in enumerate(report["questions_for_author"], 1):
                lines.append(f"  {j}. {q}")
            lines.append("")

    # === 4. 魔鬼代言人 ===
    da = result.get("devils_advocate_report")
    if da:
        lines.append("---")
        lines.append("")
        lines.append("## 3. 魔鬼代言人报告")
        lines.append("")

        if da.get("strongest_counter_argument"):
            lines.append("### 最强反证")
            lines.append("")
            lines.append(da["strongest_counter_argument"])
            lines.append("")

        if da.get("issues", {}).get("CRITICAL"):
            lines.append(f"### CRITICAL 问题 ({len(da['issues']['CRITICAL'])} 个)")
            lines.append("")
            for j, issue in enumerate(da["issues"]["CRITICAL"], 1):
                dim = issue.get("dimension", "")
                desc = issue.get("description", "")
                loc = issue.get("location", "")
                lines.append(f"  {j}. **[{dim}]** {desc}")
                if loc:
                    lines.append(f"     - 位置: {loc}")
            lines.append("")

        if da.get("issues", {}).get("MAJOR"):
            lines.append(f"### MAJOR 问题 ({len(da['issues']['MAJOR'])} 个)")
            lines.append("")
            for j, issue in enumerate(da["issues"]["MAJOR"], 1):
                dim = issue.get("dimension", "")
                desc = issue.get("description", "")
                loc = issue.get("location", "")
                lines.append(f"  {j}. **[{dim}]** {desc}")
                if loc:
                    lines.append(f"     - 位置: {loc}")
            lines.append("")

        if da.get("issues", {}).get("MINOR"):
            lines.append(f"### MINOR 问题 ({len(da['issues']['MINOR'])} 个)")
            lines.append("")
            for j, issue in enumerate(da["issues"]["MINOR"], 1):
                dim = issue.get("dimension", "")
                desc = issue.get("description", "")
                loc = issue.get("location", "")
                lines.append(f"  {j}. [{dim}] {desc}")
            lines.append("")

        if da.get("ignored_alternatives"):
            lines.append("### 被忽略的替代解释")
            lines.append("")
            for j, alt in enumerate(da["ignored_alternatives"], 1):
                lines.append(f"  {j}. {alt}")
            lines.append("")

        if da.get("missing_stakeholders"):
            lines.append("### 缺失的利益相关者视角")
            lines.append("")
            for j, s in enumerate(da["missing_stakeholders"], 1):
                lines.append(f"  {j}. {s}")
            lines.append("")

    # === 5. 编辑综合 ===
    consensus = result.get("consensus_analysis", {})
    if consensus:
        lines.append("---")
        lines.append("")
        lines.append("## 4. 编辑综合")
        lines.append("")
        if consensus.get("summary"):
            lines.append("### 共识总结")
            lines.append("")
            lines.append(consensus["summary"])
            lines.append("")
        if consensus.get("devils_advocate_handling"):
            lines.append("### 对 CRITICAL 问题的处理")
            lines.append("")
            lines.append(consensus["devils_advocate_handling"])
            lines.append("")

    # === 6. 修订路线图 ===
    roadmap = result.get("revision_roadmap", {})
    if roadmap:
        lines.append("---")
        lines.append("")
        lines.append("## 5. 修订路线图")
        lines.append("")

        priority_labels = {
            "priority_1_structural": ("Priority 1 — 必须修改 (Must Fix)", "影响核心结论的方法论或逻辑问题"),
            "priority_2_content": ("Priority 2 — 应当修改 (Should Fix)", "补充内容但不改变结论"),
            "priority_3_formatting": ("Priority 3 — 建议修改 (Nice to Fix)", "语言和格式问题"),
        }

        total_days = 0
        for key, (label, desc) in priority_labels.items():
            items = roadmap.get(key, [])
            if not items:
                continue
            lines.append(f"### {label}")
            lines.append(f"*{desc}*")
            lines.append("")
            for j, item in enumerate(items, 1):
                if isinstance(item, dict):
                    text = item.get("item", "")
                    source = item.get("source", "")
                    effort = item.get("effort", "")
                    source_str = f" [来源: {source}]" if source else ""
                    effort_str = f" (预计: {effort})" if effort else ""
                    lines.append(f"  {j}. {text}{source_str}{effort_str}")
                    # 提取工时用于合计
                    if effort:
                        import re
                        nums = re.findall(r'(\d+)', effort)
                        if nums:
                            total_days += int(nums[0])
                else:
                    lines.append(f"  {j}. {item}")
            lines.append("")

        if total_days > 0:
            lines.append(f"**预计总编辑工时: {total_days} 天**")
            lines.append("")

    # === 页脚 ===
    lines.append("---")
    lines.append("")
    lines.append("*本报告由 AI 学术论文审稿系统自动生成，仅供参考。最终审稿意见请以领域专家意见为准。*")

    md_content = "\n".join(lines)

    # 保存到文件
    if output_path:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(md_content)

    return md_content
