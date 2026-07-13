import json

from paper_reviewer.agents import field_analyst
from paper_reviewer import graph


class FakeMessage:
    def __init__(self, content: str):
        self.content = content


class FakeLLM:
    def invoke(self, _prompt):
        return FakeMessage(json.dumps({
            "primary_discipline": "AI",
            "secondary_disciplines": ["Education"],
            "research_paradigm": "mixed",
            "methodology_type": "experiment",
            "target_journal_tier": "Q2",
            "reviewer_configs": [],
        }))


class FakePaperIndex:
    def __init__(self, _paper):
        self.chunks = ["chunk"] * 8

    def retrieve(self, _query, top_k=5):
        return "retrieved context"


def test_field_analyst_does_not_return_non_serializable_rag_index(monkeypatch):
    monkeypatch.setattr(field_analyst, "get_llm", lambda: FakeLLM())

    import paper_reviewer.rag.retriever as retriever
    monkeypatch.setattr(retriever, "PaperIndex", FakePaperIndex)

    result = field_analyst.field_analyst_node({
        "paper": "long paper " * 400,
        "paper_title": "Title",
    })

    assert "rag_index" not in result


def test_reviewer_lambda_builds_rag_index_outside_checkpoint_state(monkeypatch):
    import paper_reviewer.rag.retriever as retriever
    monkeypatch.setattr(retriever, "PaperIndex", FakePaperIndex)
    graph._RAG_INDEX_CACHE.clear()

    captured = {}

    def reviewer_node(_state, rag_index=None):
        captured["rag_index"] = rag_index
        return {"review": "ok"}

    wrapped = graph._make_reviewer_lambda(reviewer_node)
    result = wrapped({
        "paper": "long paper " * 400,
        "paper_title": "Title",
        "rag_index": None,
    })

    assert result == {"review": "ok"}
    assert isinstance(captured["rag_index"], FakePaperIndex)
