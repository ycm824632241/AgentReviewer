# Resume Review Jobs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add manual review resume after service restart and persist review task status in SQLite.

**Architecture:** Keep LangGraph SQLite checkpoints as the source of graph execution recovery. Add a small `review_jobs` table in the same SQLite database for product-level task status, progress, errors, and history display. The FastAPI layer bridges checkpoint state, job rows, in-memory `_task_status`, SSE progress, and the React UI.

**Tech Stack:** FastAPI, LangGraph `SqliteSaver`, SQLite, React 18, TypeScript, Vite, pytest.

## Global Constraints

- Work in `C:\Yechen_project\Agent-AI` on `main`.
- Do not commit `.env`, `reviewer_memory.db`, build output, caches, or `.worktrees`.
- Use `stream(None, config={"configurable": {"thread_id": thread_id}})` to resume from checkpoint; a local LangGraph experiment confirmed completed nodes are not rerun.
- Preserve existing upload, progress, result, rebuttal, history, settings, and RAG diagnostic behavior.
- A completed review cannot be resumed.
- A currently running thread cannot be resumed twice.
- If a checkpoint is missing, return 404.

---

### Task 1: SQLite Review Job Store

**Files:**
- Modify: `paper_reviewer/checkpoint.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `upsert_review_job(thread_id: str, title: str = "", status: str = "running", round_number: int = 1, done: list[str] | None = None, current: str = "", error: str | None = None, db_path: str = DEFAULT_DB) -> None`
- Produces: `get_review_job(thread_id: str, db_path: str = DEFAULT_DB) -> dict | None`
- Produces: `update_review_job_progress(thread_id: str, node_name: str, db_path: str = DEFAULT_DB) -> None`
- Produces: `finish_review_job(thread_id: str, round_number: int | None = None, db_path: str = DEFAULT_DB) -> None`
- Produces: `fail_review_job(thread_id: str, error: str, db_path: str = DEFAULT_DB) -> None`
- Produces: `list_review_jobs(db_path: str = DEFAULT_DB) -> list[dict]`

- [ ] **Step 1: Write the failing tests**

```python
def test_review_job_store_persists_progress(tmp_path):
    from paper_reviewer.checkpoint import (
        get_review_job,
        update_review_job_progress,
        upsert_review_job,
    )
    db_path = str(tmp_path / "jobs.db")
    upsert_review_job("t1", title="paper.txt", status="running", round_number=1, db_path=db_path)
    update_review_job_progress("t1", "field_analyst", db_path=db_path)
    job = get_review_job("t1", db_path=db_path)
    assert job["done"] == ["field_analyst"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_web.py::TestJobStore -q`

Expected: FAIL because job-store functions do not exist.

- [ ] **Step 3: Write the minimal implementation**

Create a `review_jobs` table with columns `thread_id`, `title`, `status`, `round_number`, `done_json`, `current`, `error`, `created_at`, `updated_at`. Use JSON for `done`.

- [ ] **Step 4: Run the focused tests**

Run: `py -3.11 -m pytest tests/test_web.py::TestJobStore -q`

Expected: PASS.

### Task 2: Resume API and Backend Status Bridge

**Files:**
- Modify: `paper_reviewer/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `POST /api/resume/{thread_id}`
- Produces: `can_resume: bool` and `job_status: str | None` in `/api/result/{thread_id}`
- Consumes: job-store helpers from Task 1.

- [ ] **Step 1: Write the failing tests**

```python
def test_api_resume_rejects_completed_checkpoint(monkeypatch):
    monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"editorial_decision": "Accept"}, raising=False)
    r = client.post("/api/resume/completed")
    assert r.status_code == 409
```

```python
def test_api_resume_starts_checkpoint_resume(monkeypatch):
    calls = []
    monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"paper": "p", "round_number": 1, "reviewer_configs": []}, raising=False)
    monkeypatch.setattr(web, "_checkpoint_next", lambda _thread_id, _saved: ("eic",), raising=False)
    monkeypatch.setattr(web, "_run_resume", lambda thread_id: calls.append(thread_id), raising=False)
    r = client.post("/api/resume/resumable")
    assert r.status_code == 200
    assert r.json()["status"] == "resume_started"
    assert calls == ["resumable"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_web.py::TestApiResume -q`

Expected: FAIL because `/api/resume/{thread_id}` and helpers do not exist.

- [ ] **Step 3: Write the minimal implementation**

Add `_is_active_task`, `_checkpoint_next`, `_status_from_checkpoint`, `_run_resume`, and `/api/resume/{thread_id}`. Use `build_review_graph_with_checkpoint()` for round one and `build_rebuttal_graph()` for round two. `_run_resume` calls `graph_app.stream(None, config=config)` and updates `_task_status` plus `review_jobs`.

- [ ] **Step 4: Run the focused tests**

Run: `py -3.11 -m pytest tests/test_web.py::TestApiResume tests/test_web.py::TestApiEndpoints -q`

Expected: PASS.

### Task 3: History and Frontend Resume Controls

**Files:**
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_react_display.py`

**Interfaces:**
- Consumes: `/api/resume/{thread_id}`
- Consumes: `ReviewResultResponse.can_resume`
- Consumes: `HistoryItem.status`, `HistoryItem.can_resume`
- Produces: `resumeReview(threadId: string): Promise<{status: string; thread_id: string}>`

- [ ] **Step 1: Write the failing frontend static test**

```python
def test_frontend_exposes_continue_review_button():
    app = read_frontend("App.tsx")
    api = read_frontend("api.ts")
    types = read_frontend("types.ts")
    assert "resumeReview" in api
    assert "can_resume" in types
    assert "继续审稿" in app
```

- [ ] **Step 2: Run test to verify it fails**

Run: `py -3.11 -m pytest tests/test_react_display.py::test_frontend_exposes_continue_review_button -q`

Expected: FAIL because the frontend resume API and buttons do not exist.

- [ ] **Step 3: Write the minimal implementation**

Add `resumeReview` API wrapper, `can_resume` types, `handleResumeReview`, a result/progress panel button, and a history-row resume action. After resume succeeds, clear terminal errors and reconnect SSE with `listenProgress(threadId)`.

- [ ] **Step 4: Run frontend tests and build**

Run: `py -3.11 -m pytest tests/test_react_display.py -q`

Run: `npm run build`

Expected: PASS and successful build.

### Task 4: Full Verification and Git Commit

**Files:**
- Modify only files touched above.

**Interfaces:**
- Consumes all tests from Tasks 1-3.

- [ ] **Step 1: Run backend tests**

Run: `py -3.11 -m pytest tests -q -k "not end_to_end"`

Expected: `0 failed`.

- [ ] **Step 2: Run frontend build**

Run: `npm run build` in `frontend`.

Expected: exit code `0`.

- [ ] **Step 3: Run Git whitespace check**

Run: `git diff --check`

Expected: exit code `0`.

- [ ] **Step 4: Commit**

```bash
git add paper_reviewer/checkpoint.py paper_reviewer/web.py frontend/src/api.ts frontend/src/types.ts frontend/src/App.tsx frontend/src/styles.css tests/test_web.py tests/test_react_display.py docs/superpowers/plans/2026-07-30-resume-review-jobs.md
git commit -m "feat(web): resume interrupted review jobs"
```
