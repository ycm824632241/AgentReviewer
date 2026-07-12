"""
测量 RAG 对 token 消耗的实际影响。
对比同一论文在 RAG 开启/关闭下的输入大小。
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from paper_reviewer.main import read_text_from_file, review_paper


def estimate_tokens(text: str) -> int:
    """粗略估算 token 数：中文约 1.5 字/token，英文约 4 字符/token。"""
    cn_chars = sum(1 for c in text if '一' <= c <= '鿿')
    other_chars = len(text) - cn_chars
    return int(cn_chars * 1.5 + other_chars / 3.5)


def measure_review(paper_text: str, title: str, use_rag: bool) -> dict:
    """运行审稿并统计各节点输入大小。"""
    from paper_reviewer.rag.retriever import PaperIndex, _chunk_text

    paper_tokens = estimate_tokens(paper_text)
    n_chunks = len(_chunk_text(paper_text))

    # 统计各角色输入
    stats = {
        "rag_enabled": use_rag,
        "paper_tokens": paper_tokens,
        "n_chunks": n_chunks,
        "field_analyst_input": 0,
        "reviewer_input_per_person": 0,
        "total_reviewer_input": 0,
    }

    if use_rag:
        # Field Analyst: 前 2000 字 + 检索 6-12 块
        try:
            rag_index = PaperIndex(paper_text)
            n = len(rag_index.chunks)
            top_k = min(max(6, n // 4), 12)
            retrieved = rag_index.retrieve("research field discipline", top_k=top_k)
            field_input = paper_text[:2000] + "\n\n" + retrieved
            stats["field_analyst_input"] = estimate_tokens(field_input)
        except Exception:
            stats["field_analyst_input"] = paper_tokens

        # 每个 Reviewer: 检索 6-15 块
        top_k_rev = min(max(5, n_chunks // 4), 15)
        # 估算每块 ~800 字
        reviewer_chars = top_k_rev * 800
        stats["reviewer_input_per_person"] = estimate_tokens("x" * reviewer_chars)
    else:
        # 无 RAG：全部角色都收到全文
        stats["field_analyst_input"] = paper_tokens
        stats["reviewer_input_per_person"] = paper_tokens

    stats["total_reviewer_input"] = stats["reviewer_input_per_person"] * 5
    stats["total_input"] = stats["field_analyst_input"] + stats["total_reviewer_input"]

    return stats


def main():
    paper_path = sys.argv[1] if len(sys.argv) > 1 else "test2.pdf"
    paper_text = read_text_from_file(paper_path)
    title = os.path.splitext(os.path.basename(paper_path))[0]

    print(f"=== RAG 效果测量 ===")
    print(f"论文: {paper_path} ({len(paper_text)} 字符)")
    print()

    # 测量无 RAG
    stats_no_rag = measure_review(paper_text, title, use_rag=False)
    # 测量有 RAG
    stats_rag = measure_review(paper_text, title, use_rag=True)

    print(f"{'指标':<25} {'无 RAG':>12} {'有 RAG':>12} {'节省':>10}")
    print("-" * 62)

    rows = [
        ("论文总 tokens", stats_no_rag["paper_tokens"], stats_rag["paper_tokens"]),
        ("Field Analyst 输入", stats_no_rag["field_analyst_input"], stats_rag["field_analyst_input"]),
        ("单 Reviewer 输入", stats_no_rag["reviewer_input_per_person"], stats_rag["reviewer_input_per_person"]),
        ("5 Reviewer 总输入", stats_no_rag["total_reviewer_input"], stats_rag["total_reviewer_input"]),
        ("系统总输入", stats_no_rag["total_input"], stats_rag["total_input"]),
    ]

    for label, no_rag, rag in rows:
        if no_rag > 0:
            saving = (1 - rag / no_rag) * 100
            print(f"{label:<25} {no_rag:>10,} {rag:>10,} {saving:>8.1f}%")
        else:
            print(f"{label:<25} {no_rag:>10,} {rag:>10,} {'N/A':>10}")

    print()
    total_saving = (1 - stats_rag["total_input"] / stats_no_rag["total_input"]) * 100
    print(f"总 token 节省: {total_saving:.1f}%")
    print()
    print(f"RAG 分块数: {stats_rag['n_chunks']} 个 chunk")
    print(f"Reviewer 检索 top-k: {min(max(5, stats_rag['n_chunks'] // 4), 15)} 块")


if __name__ == "__main__":
    main()
