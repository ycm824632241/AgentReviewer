# Final Review Fix Report

## Changes

- `GET /` now serves `frontend/dist/index.html` when present and preserves the Jinja upload page when the build is absent. Existing Jinja routes remain explicit routes, and API routes are not handled by the SPA fallback.
- `GET /api/result/{thread_id}` now returns `404 {"detail":"thread not found"}` only when both saved state and in-memory status are absent.
- `/api/rebuttal/{thread_id}` enriches reviewer configurations with normalized `target` values for the real `EIC`, `Methodology`, `Domain`, `Perspective`, and `DevilsAdvocate` roles. The React Rebuttal selector submits `reviewer.target` and displays `reviewer.name ?? reviewer.role ?? reviewer.target`.
- The React history workflow derives completion and error status from persisted progress and resumes the single owned SSE stream only for unfinished selected threads.
- Rebuttal graph construction now runs inside the guarded background task. A synchronous build error is recorded in `_task_status[thread_id]["error"]`, so the task is not left permanently blocked with `409`.
- Upgraded build tooling with npm and moved it to `devDependencies`: `vite@8.1.4`, `typescript@7.0.2`, and `@vitejs/plugin-react@6.0.3`. Added Vite's standard `src/vite-env.d.ts` declaration for TypeScript 7 CSS side-effect imports.
- Added focused backend tests for static root hosting, Jinja fallback, unknown API results, normalized reviewer targets, and graph-build error handling.

## Commands And Results

- `node --version` -> `v24.15.0`
- `npm install --save-dev vite@latest typescript@latest @vitejs/plugin-react@latest` -> completed; npm reported `found 0 vulnerabilities`.
- `npm run build` -> passed; Vite 8.1.4 produced `dist/index.html` and bundled assets.
- `npm audit --package-lock-only` -> `found 0 vulnerabilities`.
- `py -3.11 -m pytest tests/test_web.py tests/test_checkpoint.py tests/test_rebuttal.py -v` -> `43 passed, 1 warning` (existing Starlette/httpx deprecation warning).
- `git diff --check` -> passed; no whitespace errors.

## Final Re-Review Fixes

### Changes

- Added checkpoint-completion detection for final synthesizer output and return durable completed progress from `GET /api/result/{thread_id}` when process-local task status is unavailable.
- Made `GET /progress/{thread_id}` and `GET /api/progress/{thread_id}` terminal for checkpoint-completed, unknown, and inactive checkpoint-only threads while preserving the existing in-memory stream loop for active tasks.
- Seeded upload task status before scheduling the background review so an immediately connected progress stream remains active.
- Added focused API regressions for restart-safe result progress, unknown SSE IDs, and checkpoint-completed SSE IDs.

### Commands And Results

- `py -3.11 -m pytest tests/test_web.py -v -k "checkpoint_completed or unknown_thread_emits_error"` -> failed as expected before the fix: unknown progress thread timed out in the SSE loop.
- `py -3.11 -m pytest tests/test_web.py -v -k "marks_completed_checkpoint or unknown_thread_emits_error or completed_checkpoint_emits_finished"` -> `3 passed, 33 deselected, 1 warning`.
- `py -3.11 -m pytest tests/test_web.py tests/test_checkpoint.py tests/test_rebuttal.py -v` -> `46 passed, 1 warning` (existing Starlette/httpx deprecation warning).
- `npm run build` -> not run; this change only modifies backend Python and backend tests.
- `git diff --check` -> passed; no whitespace errors.
