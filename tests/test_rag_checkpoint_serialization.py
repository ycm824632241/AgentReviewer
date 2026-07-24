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
    graph.clear_rag_cache()

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


def test_field_analyst_and_reviewer_share_cached_rag_index(monkeypatch):
    import paper_reviewer.rag.retriever as retriever

    graph.clear_rag_cache()
    monkeypatch.setattr(field_analyst, "get_llm", lambda: FakeLLM())

    calls = {"count": 0}

    class CountingPaperIndex(FakePaperIndex):
        def __init__(self, paper):
            calls["count"] += 1
            super().__init__(paper)
            self.diagnostics = {
                "paper_chars": len(paper),
                "chunk_count": len(self.chunks),
                "chunk_embedding_status": "success",
            }

    monkeypatch.setattr(retriever, "PaperIndex", CountingPaperIndex)
    state = {
        "paper": "long paper " * 400,
        "paper_title": "Title",
    }

    field_analyst.field_analyst_node(state)
    graph._get_rag_index(state)

    assert calls["count"] == 1


def test_rag_index_build_failure_is_not_cached_as_permanent_none(monkeypatch):
    import paper_reviewer.rag.retriever as retriever

    calls = {"count": 0}

    class FlakyPaperIndex(FakePaperIndex):
        def __init__(self, paper):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("temporary embedding failure")
            super().__init__(paper)

    monkeypatch.setattr(retriever, "PaperIndex", FlakyPaperIndex)
    graph.clear_rag_cache()
    state = {"paper": "long paper " * 400}

    assert graph._get_rag_index(state) is None
    second = graph._get_rag_index(state)

    assert isinstance(second, FlakyPaperIndex)
    assert calls["count"] == 2
    diagnostics = graph.get_rag_diagnostics(state["paper"])
    assert diagnostics["chunk_embedding_status"] == "success"


def test_clear_rag_cache_clears_indexes_and_diagnostics():
    graph._RAG_INDEX_CACHE["paper"] = object()
    graph._RAG_DIAGNOSTICS_CACHE["paper"] = {"chunk_embedding_status": "success"}

    graph.clear_rag_cache()

    assert graph._RAG_INDEX_CACHE == {}
    assert graph._RAG_DIAGNOSTICS_CACHE == {}
