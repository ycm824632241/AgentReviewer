import argparse
import json
import os
import sys

# 添加项目根目录到 path（复用旧 Reviewer.py 的 .env 加载逻辑）
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from paper_reviewer.graph import build_review_graph
from paper_reviewer.state import ReviewState


def read_text_from_file(path: str) -> str:
    """读取 .txt 或 .pdf 文件（复用旧逻辑）。"""
    ext = os.path.splitext(path)[1].lower()
    if ext == ".txt":
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    if ext == ".pdf":
        try:
            import PyPDF2
        except ImportError:
            raise ImportError("读取 PDF 需要 PyPDF2：pip install PyPDF2")
        reader = PyPDF2.PdfReader(path)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        if not text.strip():
            raise ValueError(f"无法从 PDF 提取文本：{path}")
        return text
    raise ValueError(f"不支持的格式 {ext}，仅支持 .txt 和 .pdf")


def review_paper(paper_text: str, title: str = "", use_rag: bool = True,
                 on_node_complete=None) -> dict:
    """
    运行完整审稿流程并返回结构化结果。

    Args:
        paper_text: 论文全文
        title: 论文标题
        use_rag: 是否启用 RAG（长论文建议开启）
        on_node_complete: 节点完成回调 func(node_name)，用于进度显示
    """
    app = build_review_graph(use_rag=use_rag)

    initial_state = ReviewState(
        paper=paper_text,
        paper_title=title,
        language="zh",
        rag_index=None,
        primary_discipline="",
        secondary_disciplines=[],
        research_paradigm="",
        methodology_type="",
        target_journal_tier="",
        reviewer_configs=[],
        eic_report=None,
        methodology_report=None,
        domain_report=None,
        perspective_report=None,
        devils_advocate_report=None,
        editorial_decision="",
        consensus_analysis=None,
        dimension_scores=None,
        revision_roadmap=None,
        round_number=1,
        rebuttal_text=None,
        rebuttal_target=None,
        rebuttal_history=[],
    )

    # stream 返回每个节点的输出；累积所有 chunk 得到完整结果
    result = {"paper": paper_text, "paper_title": title}  # 保留初始信息
    for chunk in app.stream(initial_state):
        if on_node_complete:
            for node_name in chunk:
                on_node_complete(node_name)
        # 累积每个节点的输出（每个 chunk 只含当前节点的 key）
        for node_output in chunk.values():
            if isinstance(node_output, dict):
                result.update(node_output)

    # 移除不可序列化对象
    result.pop("rag_index", None)
    return result


def format_output(result: dict) -> str:
    """将审稿结果格式化为人类可读的 Markdown 文本。"""
    lines = []
    lines.append("# 学术论文审稿报告")
    lines.append("")

    # 1. 审稿团队配置
    if result.get("reviewer_configs"):
        lines.append("## 1. 审稿团队配置")
        for i, cfg in enumerate(result["reviewer_configs"], 1):
            lines.append(f"  {i}. [{cfg['role']}] {cfg['identity']}")
        lines.append("")

    # 2. 各审稿人报告
    lines.append("## 2. 各审稿人报告")
    reviewer_sections = [
        ("eic_report", "EIC"),
        ("methodology_report", "方法论审稿人"),
        ("domain_report", "领域专家"),
        ("perspective_report", "跨学科视角"),
    ]
    for idx, (role_key, label) in enumerate(reviewer_sections, 1):
        report = result.get(role_key)
        if not report:
            continue
        lines.append(f"  2.{idx} {label}")
        lines.append(f"     - 推荐决定: {report.get('recommendation', 'N/A')}")
        lines.append(f"     - 置信度: {report.get('confidence', 'N/A')}/5")
        if report.get("dimension_scores"):
            lines.append("     - 维度分数:")
            for dim, score in report["dimension_scores"].items():
                lines.append(f"       - {dim}: {score}")
        lines.append(f"     - 加权平均: {report.get('weighted_average', 'N/A')}")
        lines.append("")

    # 3. 魔鬼代言人
    da = result.get("devils_advocate_report")
    if da:
        lines.append("## 3. 魔鬼代言人报告")
        if da.get("CRITICAL"):
            lines.append(f"  CRITICAL 问题 ({len(da['CRITICAL'])} 个):")
            for i, issue in enumerate(da["CRITICAL"], 1):
                dim = issue.get("dimension", "")
                desc = issue.get("description", "")
                loc = issue.get("location", "")
                lines.append(f"    {i}. [{dim}] {desc[:120]}")
                lines.append(f"       位置: {loc}")
        if da.get("strongest_counter_argument"):
            sca = da["strongest_counter_argument"]
            lines.append(f"  最强反证: {sca[:200]}")
        lines.append("")

    # 4. 编辑综合
    lines.append("## 4. 编辑综合")
    lines.append(f"  编辑决定: {result.get('editorial_decision', 'N/A')}")
    lines.append("")

    if result.get("dimension_scores"):
        lines.append("  最终维度分数:")
        for dim, score in result["dimension_scores"].items():
            lines.append(f"    - {dim}: {score}")
        lines.append("")

    if result.get("revision_roadmap"):
        lines.append("  修订路线图:")
        for priority, items in result["revision_roadmap"].items():
            if isinstance(items, list):
                lines.append(f"    [{priority}]")
                for i, item in enumerate(items, 1):
                    if isinstance(item, dict):
                        effort = item.get('effort', '')
                        source = item.get('source', '')
                        effort_str = f" (预计: {effort})" if effort else ""
                        source_str = f" [来源: {source}]" if source else ""
                        lines.append(f"      {i}. {item.get('item', '')}{effort_str}{source_str}")
                    else:
                        lines.append(f"      {i}. {item}")
                lines.append("")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="学术论文多角色审稿系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  py -3.11 -m paper_reviewer.main -f paper.txt
  py -3.11 -m paper_reviewer.main -f paper.pdf --json > result.json
  py -3.11 -m paper_reviewer.main -f long_paper.txt  (长文自动启用 RAG)
  py -3.11 -m paper_reviewer.main -f paper.txt --no-rag  (关闭 RAG)
        """
    )
    parser.add_argument("-f", "--file", required=True, help="论文文件路径 (.txt / .pdf)")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    parser.add_argument("--no-rag", action="store_true", help="关闭 RAG 检索（默认开启）")
    args = parser.parse_args()

    paper_text = read_text_from_file(args.file)
    title = os.path.splitext(os.path.basename(args.file))[0]

    use_rag = not args.no_rag
    print(f"[INFO] 已加载论文: {args.file} ({len(paper_text)} 字符)")
    print(f"[INFO] RAG 检索: {'开启' if use_rag else '关闭'}")
    print(f"[INFO] 开始审稿...\n")

    # 进度回调
    node_labels = {
        "field_analyst": "领域分析",
        "eic": "EIC 审稿",
        "methodology": "方法论审稿",
        "domain": "领域专家审稿",
        "perspective": "跨学科审稿",
        "devils_advocate": "魔鬼代言人挑战",
        "synthesizer": "编辑综合",
    }
    def on_node(name):
        label = node_labels.get(name, name)
        print(f"  [DONE] {label}")

    result = review_paper(paper_text, title, use_rag=use_rag, on_node_complete=on_node)

    print()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        # Secretary Agent: 生成 Markdown 报告
        from paper_reviewer.agents.secretary import generate_report
        md_path = f"{title}_review_report.md"
        generate_report(result, output_path=md_path)

        # 终端显示摘要（避免 GBK 编码问题）
        print("=== 审稿摘要 ===")
        print(f"  论文: {title} ({len(paper_text)} 字符)")
        print(f"  编辑决定: {result.get('editorial_decision', 'N/A')}")
        dim = result.get("dimension_scores", {})
        print(f"  最终分数: {dim.get('weighted_total', 'N/A')}")
        print(f"    originality: {dim.get('originality', 'N/A')} | methodology: {dim.get('methodology', 'N/A')} | evidence: {dim.get('evidence', 'N/A')}")
        print(f"    coherence: {dim.get('coherence', 'N/A')} | writing: {dim.get('writing', 'N/A')}")
        p1 = len(result.get('revision_roadmap', {}).get('priority_1_structural', []))
        p2 = len(result.get('revision_roadmap', {}).get('priority_2_content', []))
        p3 = len(result.get('revision_roadmap', {}).get('priority_3_formatting', []))
        print(f"  修订路线图: P1={p1}项, P2={p2}项, P3={p3}项")
        print()
        print(f"[INFO] 完整 Markdown 报告已保存至: {md_path}")
        print(f"[INFO] 请用 UTF-8 编辑器打开该文件查看完整报告")

    print(f"\n[DONE] 审稿完成")


if __name__ == "__main__":
    main()
