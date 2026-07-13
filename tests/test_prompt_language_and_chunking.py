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

    def fail_embed(_texts):
        raise RuntimeError("embedding 400")

    monkeypatch.setattr(retriever, "_embed", fail_embed)

    context = index.retrieve("short reviewer query")

    selected_chunks = context.split("\n\n---\n\n")
    assert selected_chunks
    assert len(selected_chunks) <= retriever._TOP_K_MAX
    assert "chunk-0" in selected_chunks


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
    monkeypatch.setenv("GITEE_API_KEY", "runtime-key")
    monkeypatch.setenv("GITEE_BASE_URL", "https://runtime-embed.example/v1")
    monkeypatch.setenv("GITEE_EMBED_MODEL", "runtime-embed-model")

    embeddings = retriever._embed(["hello"])

    assert embeddings == [[0.1, 0.2]]
    assert calls == {
        "api_key": "runtime-key",
        "base_url": "https://runtime-embed.example/v1",
        "model": "runtime-embed-model",
        "input": ["hello"],
    }
