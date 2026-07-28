# AgentReviewer Console UI And Settings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a console-style React UI with top navigation and a settings screen for LLM and Embedding API configuration.

**Architecture:** Add small FastAPI settings endpoints backed by the existing `.env` file, then extend the React app with local navigation state and a settings form. Keep Rebuttal inside the review workspace.

**Tech Stack:** FastAPI, React, Vite, TypeScript, pytest.

## Global Constraints

- Settings use `20-multi-agent-debate/.env`.
- Expose only `MIMO_BASE_URL`, `MIMO_API_KEY`, `MIMO_MODEL_DEBATER`, `GITEE_BASE_URL`, `GITEE_API_KEY`, and `GITEE_EMBED_MODEL`.
- Mask API keys in GET responses.
- No new routing library.
- Preserve existing upload, SSE progress, result rendering, Rebuttal, and history behavior.

---

### Task 1: Settings API

**Files:**
- Modify: `paper_reviewer/web.py`
- Test: `tests/test_web.py`

**Interfaces:**
- Produces: `GET /api/settings`
- Produces: `POST /api/settings`

- [ ] Write tests that monkeypatch the settings env path, verify GET masks keys, and POST writes supported keys.
- [ ] Run `py -3.11 -m pytest tests/test_web.py -v` and confirm the new tests fail because the endpoints do not exist.
- [ ] Implement `.env` parsing and writing helpers in `paper_reviewer/web.py`.
- [ ] Add `GET /api/settings` and `POST /api/settings`.
- [ ] Re-run `py -3.11 -m pytest tests/test_web.py -v`.

### Task 2: Console UI And Settings Page

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`
- Test: `tests/test_react_display.py`

**Interfaces:**
- Consumes: `GET /api/settings`
- Consumes: `POST /api/settings`

- [ ] Add frontend tests for top nav labels, settings fields, and FreeLLMAPI-style CSS markers.
- [ ] Run `py -3.11 -m pytest tests/test_react_display.py -v` and confirm the new tests fail.
- [ ] Add settings types and API functions.
- [ ] Add local navigation state and settings form to `App.tsx`.
- [ ] Restyle the app to white console panels, black primary buttons, top navigation, and segmented controls.
- [ ] Run `py -3.11 -m pytest tests/test_react_display.py -v`.
- [ ] Run `npm run build` from `frontend`.

### Task 3: Final Verification

**Files:**
- No new files.

- [ ] Run `py -3.11 -m pytest tests/test_web.py tests/test_react_display.py -v`.
- [ ] Run `npm run build` from `frontend`.
- [ ] Check `git status --short` and restore generated `__pycache__` files only.
- [ ] Commit implementation with message `feat(web): add console settings UI`.
