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
from paper_reviewer.utils import with_retry


def _make_reviewer_lambda(node_fn):
    """创建带 RAG 的审稿人 lambda，从 state 取 rag_index 并自带重试。"""
    def node_with_rag(state):
        rag_index = state.get("rag_index")
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
