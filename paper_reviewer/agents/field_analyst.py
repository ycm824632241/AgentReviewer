from langchain_core.prompts import ChatPromptTemplate
from paper_reviewer.state import ReviewState
from paper_reviewer.prompts.system_prompts import FIELD_ANALYST_SYSTEM
from paper_reviewer.utils import get_llm, _extract_json, _safe_json_loads, normalize_report

FIELD_ANALYST_OUTPUT_SCHEMA = """
输出为 JSON 格式：
{{
  "primary_discipline": "主要学科",
  "secondary_disciplines": ["交叉学科1", "交叉学科2"],
  "research_paradigm": "定量/定性/混合/理论分析/综述",
  "methodology_type": "研究方法类型",
  "target_journal_tier": "Q1/Q2/Q3/Q4",
  "reviewer_configs": [
    {{
      "role": "EIC",
      "identity": "国际高等教育研究期刊主编",
      "expertise": "高等教育政策、学术出版",
      "focus": "期刊匹配度、原创性、整体质量"
    }},
    {{
      "role": "Methodology",
      "identity": "教育统计学教授",
      "expertise": "准实验设计、结构方程模型",
      "focus": "研究设计严谨性、统计方法、可重复性"
    }},
    {{
      "role": "Domain",
      "identity": "AI教育应用领域研究员",
      "expertise": "智能辅导系统、学习分析",
      "focus": "文献覆盖、理论框架、领域贡献"
    }},
    {{
      "role": "Perspective",
      "identity": "跨学科教育技术研究者",
      "expertise": "教育技术创新、政策影响评估",
      "focus": "跨学科连接、实践影响、挑战假设"
    }},
    {{
      "role": "DevilsAdvocate",
      "identity": "批判性方法论学者",
      "expertise": "研究逻辑、因果推断、认知偏差",
      "focus": "核心论点挑战、逻辑谬误检测、最强反证"
    }}
  ]
}}
"""

def field_analyst_node(state: ReviewState) -> ReviewState:
    llm = get_llm()
    # Field Analyst 也使用 RAG：先建索引，再检索相关段落
    from paper_reviewer.rag.retriever import PaperIndex

    rag_index = None
    paper_text_for_analysis = state["paper"]

    if len(state["paper"]) > 3000:
        try:
            rag_index = PaperIndex(state["paper"])
            # 检索更多段落：Field Analyst 需要充分了解论文全貌才能精准配置审稿团
            # 动态计算：论文越长检索越多，但控制总量避免 token 溢出
            n_chunks = len(rag_index.chunks)
            top_k = min(max(6, n_chunks // 4), 12)  # 6-12 块，动态
            retrieved = rag_index.retrieve(
                "research field discipline domain methodology theoretical framework contributions",
                top_k=top_k
            )
            # 取论文前 2000 字（通常含标题、摘要、引言）+ 检索结果
            paper_text_for_analysis = state["paper"][:2000] + "\n\n---\n\n" + retrieved
        except Exception:
            rag_index = None  # embedding 失败时退化为全文

    prompt = ChatPromptTemplate.from_messages([
        ("system", FIELD_ANALYST_SYSTEM + "\n\n" + FIELD_ANALYST_OUTPUT_SCHEMA),
        ("human", "请分析以下论文并生成审稿团队配置卡：\n\n标题：{title}\n\n论文内容：\n{paper}"),
    ])
    result = llm.invoke(prompt.format(
        title=state.get("paper_title", ""),
        paper=paper_text_for_analysis
    ))
    import json
    analysis = _safe_json_loads(_extract_json(result.content))
    return analysis
