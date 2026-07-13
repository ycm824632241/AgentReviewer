import hashlib
from typing import List

from langgraph.graph import StateGraph, END
from paper_reviewer.checkpoint import get_checkpointer
from paper_reviewer.state import ReviewState
from paper_reviewer.agents.field_analyst import field_analyst_node
from paper_reviewer.agents.eic import eic_node
from paper_reviewer.agents.methodology_reviewer import methodology_reviewer_node
from paper_reviewer.agents.domain_reviewer import domain_reviewer_node
from paper_reviewer.agents.perspective_reviewer import perspective_reviewer_node
from paper_reviewer.agents.devils_advocate import devils_advocate_node
from paper_reviewer.agents.synthesizer import synthesizer_node
from paper_reviewer.agents.rebuttal_reviewer import build_rebuttal_report_node
from paper_reviewer.utils import with_retry

_RAG_INDEX_CACHE = {}


def _get_rag_index(state: dict):
    """Build a process-local RAG index without storing it in checkpoint state."""
    paper = state.get("paper", "")
    if len(paper) <= 3000:
        return None

    cache_key = hashlib.sha256(paper.encode("utf-8")).hexdigest()
    if cache_key not in _RAG_INDEX_CACHE:
        try:
            from paper_reviewer.rag.retriever import PaperIndex
            _RAG_INDEX_CACHE[cache_key] = PaperIndex(paper)
        except Exception:
            _RAG_INDEX_CACHE[cache_key] = None
    return _RAG_INDEX_CACHE[cache_key]


def _make_reviewer_lambda(node_fn):
    """创建带 RAG 的审稿人 lambda；索引只保存在进程内缓存，不进入 checkpoint。"""
    def node_with_rag(state):
        rag_index = state.get("rag_index") or _get_rag_index(state)
        return node_fn(state, rag_index)
    return with_retry(node_with_rag)


def build_review_graph(use_rag: bool = True):
    """
    构建审稿流程图。

    Args:
        use_rag: 是否启用 RAG 检索（长论文建议开启，节省 token 并提升审稿质量）
    """
    graph = StateGraph(ReviewState)

    # Phase 0: 领域分析（始终需要全文来识别学科，同时构建 RAG 索引）
    graph.add_node("field_analyst", with_retry(field_analyst_node))

    # Phase 1: 5 个并行审稿人
    if use_rag:
        graph.add_node("eic", _make_reviewer_lambda(eic_node))
        graph.add_node("methodology", _make_reviewer_lambda(methodology_reviewer_node))
        graph.add_node("domain", _make_reviewer_lambda(domain_reviewer_node))
        graph.add_node("perspective", _make_reviewer_lambda(perspective_reviewer_node))
        graph.add_node("devils_advocate", _make_reviewer_lambda(devils_advocate_node))
    else:
        graph.add_node("eic", with_retry(eic_node))
        graph.add_node("methodology", with_retry(methodology_reviewer_node))
        graph.add_node("domain", with_retry(domain_reviewer_node))
        graph.add_node("perspective", with_retry(perspective_reviewer_node))
        graph.add_node("devils_advocate", with_retry(devils_advocate_node))

    # Phase 2: 编辑综合
    graph.add_node("synthesizer", with_retry(synthesizer_node))

    # Phase 0 → Phase 1
    graph.add_edge("field_analyst", "eic")
    graph.add_edge("field_analyst", "methodology")
    graph.add_edge("field_analyst", "domain")
    graph.add_edge("field_analyst", "perspective")
    graph.add_edge("field_analyst", "devils_advocate")

    # Phase 1 → Phase 2
    graph.add_edge("eic", "synthesizer")
    graph.add_edge("methodology", "synthesizer")
    graph.add_edge("domain", "synthesizer")
    graph.add_edge("perspective", "synthesizer")
    graph.add_edge("devils_advocate", "synthesizer")

    # Phase 2 → END
    graph.add_edge("synthesizer", END)

    graph.set_entry_point("field_analyst")
    return graph.compile()


def build_review_graph_with_checkpoint(use_rag: bool = True, db_path: str = None):
    """
    编译带 SqliteSaver checkpointer 的图（供 web 使用，支持断点恢复）。

    Args:
        use_rag: 是否启用 RAG 检索（长论文建议开启，节省 token 并提升审稿质量）
        db_path: sqlite 数据库路径；None 使用默认 reviewer_memory.db
    """
    graph = StateGraph(ReviewState)

    # Phase 0: 领域分析（始终需要全文来识别学科，同时构建 RAG 索引）
    graph.add_node("field_analyst", with_retry(field_analyst_node))

    # Phase 1: 5 个并行审稿人
    if use_rag:
        graph.add_node("eic", _make_reviewer_lambda(eic_node))
        graph.add_node("methodology", _make_reviewer_lambda(methodology_reviewer_node))
        graph.add_node("domain", _make_reviewer_lambda(domain_reviewer_node))
        graph.add_node("perspective", _make_reviewer_lambda(perspective_reviewer_node))
        graph.add_node("devils_advocate", _make_reviewer_lambda(devils_advocate_node))
    else:
        graph.add_node("eic", with_retry(eic_node))
        graph.add_node("methodology", with_retry(methodology_reviewer_node))
        graph.add_node("domain", with_retry(domain_reviewer_node))
        graph.add_node("perspective", with_retry(perspective_reviewer_node))
        graph.add_node("devils_advocate", with_retry(devils_advocate_node))

    # Phase 2: 编辑综合
    graph.add_node("synthesizer", with_retry(synthesizer_node))

    # Phase 0 → Phase 1
    graph.add_edge("field_analyst", "eic")
    graph.add_edge("field_analyst", "methodology")
    graph.add_edge("field_analyst", "domain")
    graph.add_edge("field_analyst", "perspective")
    graph.add_edge("field_analyst", "devils_advocate")

    # Phase 1 → Phase 2
    graph.add_edge("eic", "synthesizer")
    graph.add_edge("methodology", "synthesizer")
    graph.add_edge("domain", "synthesizer")
    graph.add_edge("perspective", "synthesizer")
    graph.add_edge("devils_advocate", "synthesizer")

    # Phase 2 → END
    graph.add_edge("synthesizer", END)

    graph.set_entry_point("field_analyst")

    cp = get_checkpointer(db_path) if db_path else get_checkpointer()
    return graph.compile(checkpointer=cp)


# ── Rebuttal conditional-entry graph ────────────────────────────────────────
_REVIEWER_NAMES = ["eic", "methodology", "domain", "perspective", "devils_advocate"]


def _route_rebuttal(state: dict) -> List[str]:
    """根据 rebuttal_target 决定重跑哪些审稿人，然后进入 synthesizer。"""
    target = state.get("rebuttal_target", "all")
    if target == "all":
        return list(_REVIEWER_NAMES)
    if target in _REVIEWER_NAMES:
        return [target]
    return list(_REVIEWER_NAMES)


def build_rebuttal_graph(db_path: str = None):
    """编译含 rebuttal 路径的图。Round 1 不变；Round 2 走 rebuttal_* 节点。"""
    g = StateGraph(ReviewState)
    # Round 1 节点
    g.add_node("field_analyst", with_retry(field_analyst_node))
    for name in _REVIEWER_NAMES:
        fn = {"eic": eic_node, "methodology": methodology_reviewer_node,
              "domain": domain_reviewer_node, "perspective": perspective_reviewer_node,
              "devils_advocate": devils_advocate_node}[name]
        g.add_node(name, _make_reviewer_lambda(fn))
    g.add_node("synthesizer", with_retry(synthesizer_node))

    # Round 2 rebuttal 节点
    for name in _REVIEWER_NAMES:
        g.add_node(f"rebuttal_{name}", build_rebuttal_report_node(name))

    # 条件入口：round_number == 1 走 field_analyst（它构建 reviewer_configs/rag_index）；>= 2 走 rebuttal_* 节点
    def route_entry(state: dict):
        if state.get("round_number", 1) == 1:
            return ["field_analyst"]
        return [f"rebuttal_{n}" for n in _route_rebuttal(state)]

    g.set_conditional_entry_point(route_entry)

    # Phase 0 → Phase 1：field_analyst 为每位审稿人生成配置后并行进入审稿人
    for name in _REVIEWER_NAMES:
        g.add_edge("field_analyst", name)

    # Round 1 审稿人 → synthesizer
    for name in _REVIEWER_NAMES:
        g.add_edge(name, "synthesizer")

    # rebuttal 审稿人 → synthesizer
    for name in _REVIEWER_NAMES:
        g.add_edge(f"rebuttal_{name}", "synthesizer")

    # synthesizer → END
    g.add_edge("synthesizer", END)

    cp = get_checkpointer(db_path) if db_path else get_checkpointer()
    return g.compile(checkpointer=cp)
