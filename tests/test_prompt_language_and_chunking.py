from paper_reviewer.prompts import system_prompts
from paper_reviewer.rag import retriever
from paper_reviewer.rag.retriever import PaperIndex, _chunk_text


def test_reviewer_system_prompts_require_chinese_output():
    prompt_names = [
        "FIELD_ANALYST_SYSTEM",
        "EIC_SYSTEM",
        "METHODOLOGY_REVIEWER_SYSTEM",
        "DOMAIN_REVIEWER_SYSTEM",
        "PERSPECTIVE_REVIEWER_SYSTEM",
        "DEVILS_ADVOCATE_SYSTEM",
        "SYNTHESIZER_SYSTEM",
    ]

    for name in prompt_names:
        prompt = getattr(system_prompts, name)
        assert "必须使用中文输出" in prompt


def test_chunk_text_splits_single_oversized_paragraph():
    text = "A" * 2400

    chunks = _chunk_text(text, size=500, overlap=50)

    assert len(chunks) > 1
    assert max(len(chunk) for chunk in chunks) <= 550


def test_default_chunk_size_keeps_context_without_giant_requests():
    text = "A" * 2400

    chunks = _chunk_text(text)

    assert retriever._CHUNK_SIZE == 1000
    assert retriever._CHUNK_OVERLAP == 150
    assert len(chunks) <= 4
    assert max(len(chunk) for chunk in chunks) <= retriever._CHUNK_SIZE


def test_retrieve_falls_back_when_query_embedding_fails(monkeypatch):
    index = PaperIndex.__new__(PaperIndex)
    index.chunks = [f"chunk-{i}" for i in range(30)]
    index.embeddings = [[0.1] for _ in index.chunks]
    index.diagnostics = {
        "query_embedding_failures": 0,
        "fallback_used": False,
    }

    def fail_embed(_texts):
        raise RuntimeError("embedding 400")

    monkeypatch.setattr(retriever, "_embed", fail_embed)

    context = index.retrieve("short reviewer query")

    selected_chunks = context.split("\n\n---\n\n")
    assert selected_chunks
    assert len(selected_chunks) <= retriever._TOP_K_MAX
    assert "chunk-0" in selected_chunks
    assert index.diagnostics["query_embedding_failures"] == 1
    assert index.diagnostics["fallback_used"] is True


def test_embed_uses_current_embedding_environment(monkeypatch):
    calls = {}

    class StaleClient:
        class embeddings:
            @staticmethod
            def create(*_args, **_kwargs):
                raise AssertionError("stale embedding client was used")

    class FakeClient:
        def __init__(self, api_key, base_url):
            calls["api_key"] = api_key
            calls["base_url"] = base_url
            self.embeddings = self

        def create(self, model, input):
            calls["model"] = model
            calls["input"] = input

            class Item:
                embedding = [0.1, 0.2]

            class Response:
                data = [Item()]

            return Response()

    monkeypatch.setattr(retriever, "_client", StaleClient(), raising=False)
    monkeypatch.setattr(retriever, "OpenAI", FakeClient)
    monkeypatch.setenv("EMBEDDING_API_KEY", "runtime-key")
    monkeypatch.setenv("EMBEDDING_BASE_URL", "https://runtime-embed.example/v1")
    monkeypatch.setenv("EMBEDDING_MODEL", "runtime-embed-model")

    embeddings = retriever._embed(["hello"])

    assert embeddings == [[0.1, 0.2]]
    assert calls == {
        "api_key": "runtime-key",
        "base_url": "https://runtime-embed.example/v1",
        "model": "runtime-embed-model",
        "input": ["hello"],
    }


def test_embed_falls_back_to_legacy_embedding_environment(monkeypatch):
    calls = {}

    class FakeClient:
        def __init__(self, api_key, base_url):
            calls["api_key"] = api_key
            calls["base_url"] = base_url
            self.embeddings = self

        def create(self, model, input):
            calls["model"] = model

            class Item:
                embedding = [0.3]

            class Response:
                data = [Item()]

            return Response()

    monkeypatch.setattr(retriever, "OpenAI", FakeClient)
    monkeypatch.delenv("EMBEDDING_API_KEY", raising=False)
    monkeypatch.delenv("EMBEDDING_BASE_URL", raising=False)
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    monkeypatch.setenv("GITEE_API_KEY", "legacy-key")
    monkeypatch.setenv("GITEE_BASE_URL", "https://legacy-embed.example/v1")
    monkeypatch.setenv("GITEE_EMBED_MODEL", "legacy-embed-model")

    assert retriever._embed(["hello"]) == [[0.3]]
    assert calls == {
        "api_key": "legacy-key",
        "base_url": "https://legacy-embed.example/v1",
        "model": "legacy-embed-model",
    }


def test_embed_batches_large_inputs_without_reordering(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, api_key, base_url):
            self.embeddings = self

        def create(self, model, input):
            calls.append(list(input))

            class Item:
                def __init__(self, text):
                    self.embedding = [float(len(text))]

            class Response:
                def __init__(self, texts):
                    self.data = [Item(text) for text in texts]

            return Response(input)

    monkeypatch.setattr(retriever, "OpenAI", FakeClient)
    monkeypatch.setattr(retriever, "_EMBED_BATCH_MAX_ITEMS", 2)
    monkeypatch.setattr(retriever, "_EMBED_BATCH_MAX_BYTES", 12)

    embeddings = retriever._embed(["aaaa", "bbbb", "cccc", "dddd"])

    assert calls == [["aaaa", "bbbb"], ["cccc", "dddd"]]
    assert embeddings == [[4.0], [4.0], [4.0], [4.0]]


def test_paper_index_records_chunk_embedding_diagnostics(monkeypatch):
    monkeypatch.setattr(retriever, "_CHUNK_SIZE", 400)
    monkeypatch.setattr(retriever, "_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(retriever, "_EMBED_BATCH_MAX_ITEMS", 2)

    def fake_embed(texts):
        return [[float(i)] for i, _text in enumerate(texts)]

    monkeypatch.setattr(retriever, "_embed", fake_embed)

    index = PaperIndex("A" * 1300)

    assert index.diagnostics["paper_chars"] == 1300
    assert index.diagnostics["chunk_count"] == len(index.chunks)
    assert index.diagnostics["chunk_size"] == 400
    assert index.diagnostics["chunk_overlap"] == 50
    assert index.diagnostics["embedding_batches"] >= 2
    assert index.diagnostics["chunk_embedding_status"] == "success"


def test_chunk_text_enforces_hard_byte_limit_after_splitting(monkeypatch):
    monkeypatch.setattr(retriever, "_CHUNK_SIZE", 400)
    monkeypatch.setattr(retriever, "_CHUNK_OVERLAP", 50)
    monkeypatch.setattr(retriever, "_CHUNK_MAX_BYTES", 900)

    text = "汉" * 2000

    chunks = retriever._chunk_text(text, size=retriever._CHUNK_SIZE, overlap=retriever._CHUNK_OVERLAP)

    assert len(chunks) > 1
    assert max(len(chunk.encode("utf-8")) for chunk in chunks) <= retriever._CHUNK_MAX_BYTES


def test_embed_splits_single_oversized_input_before_api_call(monkeypatch):
    calls = []

    class FakeClient:
        def __init__(self, api_key, base_url):
            self.embeddings = self

        def create(self, model, input):
            calls.append(list(input))

            class Item:
                def __init__(self, text):
                    self.embedding = [float(len(text))]

            class Response:
                def __init__(self, texts):
                    self.data = [Item(text) for text in texts]

            return Response(input)

    monkeypatch.setattr(retriever, "OpenAI", FakeClient)
    monkeypatch.setattr(retriever, "_EMBED_BATCH_MAX_BYTES", 900)

    retriever._embed(["汉" * 2000])

    assert len(calls) > 1
    assert all(
        sum(len(text.encode("utf-8")) for text in batch) <= retriever._EMBED_BATCH_MAX_BYTES
        for batch in calls
    )
