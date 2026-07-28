# RAG Chunking Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make paper chunking terminate for arbitrary PDF text, preserve section context, apply bounded overlap consistently, and expose safe RAG diagnostics and deterministic fallbacks.

**Architecture:** Keep the public `PaperIndex.retrieve(query, top_k)` interface. Refactor chunking into section detection, progress-checked semantic splitting, bounded packing, and overlap application; then add serializable diagnostics to `PaperIndex` and propagate initial RAG status through `ReviewState`.

**Tech Stack:** Python 3.8+, `re`, `logging`, `pytest`, `PyPDF2`, existing OpenAI-compatible Embedding client, LangGraph typed state.

## Global Constraints

- Every returned chunk is non-empty and at most 800 characters.
- Adjacent chunks carry up to 100 characters of context overlap.
- Preserve complete section headings such as `1 引言` and `2.3 Research Design`.
- Keep `PaperIndex.retrieve(query: str, top_k: int = 5) -> str` compatible.
- Do not add BM25, rerankers, vector databases, OCR, or a new Embedding model.
- Offline unit tests must not call the real Embedding API.
- The target retriever file already has user-authored uncommitted changes; do not discard them or include unrelated workspace changes in commits.

---

### Task 1: Add failing chunking invariants

**Files:**
- Create: `tests/test_rag_retriever.py`
- Modify: none
- Test: `tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: `paper_reviewer.rag.retriever._chunk_text(text, size=800, overlap=100) -> list[str]`
- Produces: Regression coverage for termination, size, overlap, headings, and empty input.

- [ ] **Step 1: Write failing tests**

```python
import pytest

from paper_reviewer.rag.retriever import _chunk_text


def _adjacent_overlap(left: str, right: str, maximum: int = 100) -> int:
    for amount in range(min(maximum, len(left), len(right)), 0, -1):
        if left[-amount:] == right[:amount]:
            return amount
    return 0


def test_empty_text_has_no_empty_chunk():
    assert _chunk_text("") == []


def test_oversized_sentence_terminates_and_is_bounded():
    text = "方法：" + ("样本数据与统计分析" * 300) + "。"
    chunks = _chunk_text(text)
    assert len(chunks) > 1
    assert all(chunk for chunk in chunks)
    assert all(len(chunk) <= 800 for chunk in chunks)


def test_paragraph_chunks_have_overlap():
    paragraphs = [f"第{i}段 " + chr(0x4E00 + i) * 520 for i in range(1, 7)]
    chunks = _chunk_text("\n\n".join(paragraphs))
    overlaps = [_adjacent_overlap(a, b) for a, b in zip(chunks, chunks[1:])]
    assert overlaps
    assert all(90 <= amount <= 100 for amount in overlaps)


def test_section_headings_keep_their_numbers():
    text = "\n".join(
        [
            "1 引言",
            "研究背景。" * 180,
            "2.3 Research Design",
            "Method details. " * 180,
            "第一章 结论",
            "结论内容。" * 180,
        ]
    )
    joined = "\n".join(_chunk_text(text))
    assert "1 引言" in joined
    assert "2.3 Research Design" in joined
    assert "第一章 结论" in joined
```

- [ ] **Step 2: Run tests and verify the current defects**

Run: `python -m pytest tests/test_rag_retriever.py -q`

Expected: FAIL for empty input, oversized sentence recursion, paragraph overlap, and/or heading preservation.

---

### Task 2: Implement finite semantic chunking and consistent overlap

**Files:**
- Modify: `paper_reviewer/rag/retriever.py`
- Test: `tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: raw paper text and existing `_CHUNK_SIZE`, `_CHUNK_OVERLAP`.
- Produces:
  - `_split_sections(text: str) -> list[str]`
  - `_split_to_size(text: str, size: int) -> list[str]`
  - `_combine_pieces(pieces: list[str], size: int) -> list[str]`
  - `_apply_overlap(chunks: list[str], size: int, overlap: int) -> list[str]`
  - `_chunk_text(text: str, size: int = 800, overlap: int = 100) -> list[str]`

- [ ] **Step 1: Preserve complete section headings**

Replace destructive `re.split(section_pattern, ...)` with a look-ahead split:

```python
_SECTION_START_RE = re.compile(
    r"(?im)(?=^[ \t]*(?:"
    r"第[一二三四五六七八九十百千零\d]+[章节篇部分][^\n]*"
    r"|[一二三四五六七八九十]+[、.][^\n]*"
    r"|\d+(?:\.\d+)*(?:[.、]|[ \t]+)[^\n]+"
    r"|Section[ \t]+\d+(?:\.\d+)*[^\n]*"
    r"|Abstract|Introduction|Conclusion|摘要|引言|绪论|背景|方法|实验|结果|讨论|结论|总结|展望|致谢|参考文献"
    r")[ \t]*$)"
)


def _split_sections(text: str) -> List[str]:
    return [part.strip() for part in _SECTION_START_RE.split(text) if part.strip()]
```

- [ ] **Step 2: Make recursive splitting prove progress**

Use filtered pieces and fall back to a non-overlapping bounded split whenever semantic splitting does not reduce the input:

```python
def _hard_split(text: str, size: int) -> List[str]:
    return [
        text[start:start + size].strip()
        for start in range(0, len(text), size)
        if text[start:start + size].strip()
    ]


def _meaningful_parts(pattern: str, text: str) -> List[str]:
    return [part.strip() for part in re.split(pattern, text) if part.strip()]


def _split_to_size(text: str, size: int) -> List[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= size:
        return [text]

    for pattern in (r"\n\s*\n", r"(?<=[。．！？.!?])\s*"):
        pieces = _meaningful_parts(pattern, text)
        if len(pieces) >= 2 and max(map(len, pieces)) < len(text):
            return _combine_pieces(pieces, size)

    return _hard_split(text, size)
```

- [ ] **Step 3: Pack payload chunks without oversize fragments**

Ensure oversized pieces are split before adding them and merge only within the payload limit:

```python
def _combine_pieces(pieces: List[str], size: int) -> List[str]:
    bounded = []
    for piece in pieces:
        bounded.extend(_split_to_size(piece, size))

    chunks = []
    current = ""
    for piece in bounded:
        candidate = piece if not current else current + "\n" + piece
        if len(candidate) <= size:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = piece
    if current:
        chunks.append(current)
    return chunks
```

- [ ] **Step 4: Apply overlap once, after semantic packing**

Build payload chunks at `size - overlap` and prefix each later chunk with the previous payload tail:

```python
def _apply_overlap(chunks: List[str], size: int, overlap: int) -> List[str]:
    if not chunks:
        return []
    result = [chunks[0]]
    for previous, current in zip(chunks, chunks[1:]):
        separator = "\n"
        allowed = max(0, size - len(current) - len(separator))
        prefix_size = min(overlap, allowed, len(previous))
        prefix = previous[-prefix_size:] if prefix_size else ""
        result.append(prefix + separator + current if prefix else current)
    return result


def _chunk_text(text: str, size: int = _CHUNK_SIZE, overlap: int = _CHUNK_OVERLAP) -> List[str]:
    text = text.strip()
    if not text:
        return []
    overlap = max(0, min(overlap, size - 1))
    payload_size = max(1, size - overlap)
    payloads = []
    for section in _split_sections(text):
        payloads.extend(_split_to_size(section, payload_size))
    payloads = _combine_pieces(payloads, payload_size)
    return _apply_overlap(payloads, size, overlap)
```

- [ ] **Step 5: Run chunking tests**

Run: `python -m pytest tests/test_rag_retriever.py -q`

Expected: all Task 1 tests PASS and no `RecursionError`.

---

### Task 3: Add safe diagnostics and deterministic retrieval fallback

**Files:**
- Modify: `paper_reviewer/rag/retriever.py`
- Test: `tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: chunk list, `_embed(texts)`, `top_k`.
- Produces:
  - `_select_fallback_chunks(chunks: list[str], limit: int) -> list[str]`
  - `PaperIndex.diagnostics: dict[str, object]`
  - Safe fallback on index/query Embedding failure.

- [ ] **Step 1: Add failing diagnostics and fallback tests**

```python
from paper_reviewer.rag import retriever
from paper_reviewer.rag.retriever import PaperIndex


def test_index_embedding_failure_records_diagnostics(monkeypatch):
    monkeypatch.setattr(retriever, "_embed", lambda _texts: (_ for _ in ()).throw(RuntimeError("offline")))
    index = PaperIndex("段落内容。" * 900)
    assert index.embeddings is None
    assert index.diagnostics["embedding_status"] == "failed"
    assert index.diagnostics["last_error_type"] == "RuntimeError"
    result = index.retrieve("研究方法", top_k=3)
    assert result
    assert result.count("\n\n---\n\n") <= 2


def test_query_embedding_failure_uses_spread_fallback(monkeypatch):
    calls = 0

    def fake_embed(texts):
        nonlocal calls
        calls += 1
        if calls == 1:
            return [[float(i), 1.0] for i, _text in enumerate(texts)]
        raise RuntimeError("query unavailable")

    monkeypatch.setattr(retriever, "_embed", fake_embed)
    index = PaperIndex("。\n\n".join(f"第{i}段 " + ("内容" * 380) for i in range(12)))
    result = index.retrieve("研究方法", top_k=3)
    assert result
    assert index.diagnostics["query_embedding_failures"] == 1
    assert index.diagnostics["retrieval_status"] == "fallback_query_embedding_failed"
```

- [ ] **Step 2: Verify the new tests fail**

Run: `python -m pytest tests/test_rag_retriever.py -q`

Expected: FAIL because `diagnostics` and deterministic failure handling are absent.

- [ ] **Step 3: Implement deterministic spread selection**

```python
def _select_fallback_chunks(chunks: List[str], limit: int) -> List[str]:
    if not chunks or limit <= 0:
        return []
    if len(chunks) <= limit:
        return list(chunks)
    if limit == 1:
        return [chunks[0]]
    indexes = []
    for position in range(limit):
        index = round(position * (len(chunks) - 1) / (limit - 1))
        if index not in indexes:
            indexes.append(index)
    return [chunks[index] for index in indexes]
```

- [ ] **Step 4: Add diagnostics and catch external Embedding failures**

Initialize diagnostics before calling `_embed`, catch only at the external-service boundary, and keep errors secret-safe:

```python
self.diagnostics = {
    "paper_chars": len(paper_text),
    "chunk_count": len(self.chunks),
    "chunk_min_chars": min(map(len, self.chunks), default=0),
    "chunk_max_chars": max(map(len, self.chunks), default=0),
    "chunk_average_chars": (
        round(sum(map(len, self.chunks)) / len(self.chunks), 1) if self.chunks else 0.0
    ),
    "chunking_status": "success",
    "embedding_model": _EMBED_MODEL,
    "embedding_status": "skipped_single_chunk",
    "query_embedding_failures": 0,
    "retrieval_status": "not_run",
    "last_requested_top_k": None,
    "last_actual_top_k": None,
    "last_error_type": None,
}
if len(self.chunks) > 1:
    try:
        self.embeddings = _embed(self.chunks)
        self.diagnostics["embedding_status"] = "success"
    except Exception as exc:
        self.diagnostics["embedding_status"] = "failed"
        self.diagnostics["last_error_type"] = type(exc).__name__
```

In `retrieve()`, calculate `actual_k` before checking embeddings. If index vectors are unavailable, return `_select_fallback_chunks`; if query `_embed()` raises, increment `query_embedding_failures`, set `last_error_type`, and use the same spread fallback. Never include exception text or credentials in diagnostics.

- [ ] **Step 5: Run all retriever tests**

Run: `python -m pytest tests/test_rag_retriever.py -q`

Expected: all tests PASS without a real API call.

---

### Task 4: Propagate initial RAG status through the review state

**Files:**
- Modify: `paper_reviewer/state.py`
- Modify: `paper_reviewer/agents/field_analyst.py`
- Modify: `paper_reviewer/main.py`
- Modify: `paper_reviewer/web.py`
- Modify: `tests/test_checkpoint.py`
- Create or modify: `tests/test_rag_retriever.py`

**Interfaces:**
- Consumes: `PaperIndex.diagnostics`.
- Produces: `ReviewState.rag_diagnostics: dict`, including short-document and chunking-failure states.

- [ ] **Step 1: Add failing state-policy tests**

```python
from paper_reviewer.agents import field_analyst


def test_short_document_diagnostics_are_explicit(monkeypatch):
    class FakeLLM:
        def invoke(self, _prompt):
            return type("Result", (), {"content": '{"primary_discipline":"test","reviewer_configs":[]}'})()

    monkeypatch.setattr(field_analyst, "get_llm", lambda: FakeLLM())
    result = field_analyst.field_analyst_node({"paper": "短文", "paper_title": "t"})
    assert result["rag_index"] is None
    assert result["rag_diagnostics"] == {
        "enabled": False,
        "paper_chars": 2,
        "reason": "skipped_short_document",
    }
```

Update `tests/test_checkpoint.py` construction to include `rag_diagnostics={}` and assert it is present.

- [ ] **Step 2: Verify state-policy tests fail**

Run: `python -m pytest tests/test_rag_retriever.py tests/test_checkpoint.py -q`

Expected: FAIL because `rag_diagnostics` is not returned or declared.

- [ ] **Step 3: Extend and initialize `ReviewState`**

Add:

```python
rag_diagnostics: dict
```

next to `rag_index` in `paper_reviewer/state.py`, and initialize `rag_diagnostics={}` in both `paper_reviewer.main.review_paper()` and `paper_reviewer.web._run_review()`.

- [ ] **Step 4: Return explicit field-analysis diagnostics**

In `field_analyst_node()` initialize:

```python
rag_diagnostics = {
    "enabled": False,
    "paper_chars": len(state["paper"]),
    "reason": "skipped_short_document",
}
```

For long papers, build `PaperIndex`, retrieve analysis context, then copy `rag_index.diagnostics` and add `"enabled": True`. On unexpected chunking failure, use:

```python
rag_diagnostics = {
    "enabled": True,
    "paper_chars": len(state["paper"]),
    "chunking_status": "failed",
    "last_error_type": type(exc).__name__,
}
```

Return:

```python
return {**analysis, "rag_index": rag_index, "rag_diagnostics": rag_diagnostics}
```

- [ ] **Step 5: Run state and web tests**

Run: `python -m pytest tests/test_rag_retriever.py tests/test_checkpoint.py tests/test_web.py -q`

Expected: all selected tests PASS.

---

### Task 5: Real-PDF regression and full verification

**Files:**
- Modify: none unless a regression exposes a defect in Tasks 2–4.
- Test: `test2.pdf`, `test3.pdf`, entire `tests/` directory.

**Interfaces:**
- Consumes: `_chunk_text()` and existing PDF extraction behavior.
- Produces: Evidence that production-like PDF text is bounded and terminates.

- [ ] **Step 1: Run real-PDF offline regression**

Run a read-only Python check that extracts both PDFs using `PyPDF2`, calls `_chunk_text()`, and asserts:

```python
assert chunks
assert all(chunk.strip() for chunk in chunks)
assert max(map(len, chunks)) <= 800
```

Expected:

- `test2.pdf`: completes without `RecursionError`.
- `test3.pdf`: completes with all chunks at most 800 characters.

- [ ] **Step 2: Run complete test suite**

Run: `python -m pytest tests -q`

Expected: PASS. If an unrelated pre-existing failure occurs, record its exact test name and traceback separately rather than modifying unrelated code.

- [ ] **Step 3: Inspect the final diff**

Run: `git diff --check`

Expected: no whitespace errors.

Run: `git status --short`

Expected: only the intended RAG/test/state files plus pre-existing unrelated user changes. Do not commit the implementation automatically because `paper_reviewer/rag/retriever.py` already contained uncommitted user work before this task.
