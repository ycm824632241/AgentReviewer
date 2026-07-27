# UI and RAG Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the React/Vite UI branch the integration baseline while preserving safe, observable Embedding fallback and robust semantic chunking.

**Architecture:** Retain the UI branch's provider-neutral configuration, bounded Embedding batches, byte limits, and process-local `index_cache`. Replace only its chunk assembly with a progress-guaranteed, heading-preserving implementation and make `PaperIndex` retain chunks when index Embedding fails.

**Tech Stack:** Python 3.11, FastAPI, LangGraph, React/Vite, pytest.

## Global Constraints

- Preserve `frontend/`, `/api/*`, `index_cache.py`, batch limits, and checkpoint-safe index caching from `react-vite-web-ui`.
- Preserve `PaperIndex.retrieve(query, top_k)` compatibility.
- Do not call live Embedding or LLM APIs in unit tests.
- Do not modify or discard the dirty root `main` checkout during integration.

---

### Task 1: Prove the missing RAG guarantees

**Files:**
- Modify: `tests/test_prompt_language_and_chunking.py`
- Test: `tests/test_prompt_language_and_chunking.py`

- [x] Add a long-section test that asserts `1 引言` and `2.3 Research Design` remain in the resulting chunk text and every chunk is bounded by `_CHUNK_SIZE`.
- [x] Add a three-paragraph test (`size`, `短段`, `size`) that asserts each adjacent result shares at least `overlap - 1` characters.
- [x] Add an index-Embedding failure test that monkeypatches `_embed` to raise, then asserts `PaperIndex` retains chunks, records `chunk_embedding_status == "failed"`, and returns limited fallback context.
- [x] Run `py -3.11 -m pytest tests/test_prompt_language_and_chunking.py -q` and confirm the new tests fail before implementation.

### Task 2: Integrate robust chunking without removing UI-branch limits

**Files:**
- Modify: `paper_reviewer/rag/retriever.py`
- Test: `tests/test_prompt_language_and_chunking.py`

- [x] Replace destructive section splitting with a look-ahead section-start regex that retains full headings.
- [x] Split semantic payloads at `size - overlap`; if paragraph and sentence splitting do not strictly reduce the input, use bounded hard splitting.
- [x] Prefix every later payload with the previous final chunk's tail, constrained by `size`, then retain `_enforce_chunk_limits` for byte protection.
- [x] Run the focused chunking tests until green.

### Task 3: Retain chunks on Embedding failure

**Files:**
- Modify: `paper_reviewer/rag/retriever.py`
- Test: `tests/test_prompt_language_and_chunking.py`

- [x] Catch only index Embedding API exceptions in `PaperIndex.__init__`.
- [x] Preserve current diagnostic keys and add `last_error_type`, `retrieval_status`, and requested/actual `top_k` fields.
- [x] On missing embeddings or query Embedding failure, use `_select_fallback_chunks` instead of passing the full paper.
- [x] Run focused tests until green.

### Task 4: Verify UI and RAG integration

**Files:**
- Modify: `docs/superpowers/plans/2026-07-24-integrate-ui-rag.md` (mark completed steps)
- Test: `tests/`, `frontend/`

- [x] Run `py -3.11 -m pytest tests -q -k 'not end_to_end'`.
- [x] Run `npm run build` in `frontend/`.
- [x] Run a read-only `test2.pdf` chunk regression; assert no exception, nonempty chunks, character and byte limits, and bounded adjacent overlap.
- [ ] Commit the integration branch; only after verification ask to merge it into `main`.
