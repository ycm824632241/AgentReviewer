# Task 5 Report

## Changes

- Replaced the README Web section with the prescribed Vite development and FastAPI demo startup instructions.
- Added a `frontend/dist/index.html` detection message to `start_web.ps1`, before its `-CheckOnly` early exit so the smoke test reports the active serving mode.
- Ignored Vite/TypeScript generated build artifacts: `*.tsbuildinfo`, `frontend/vite.config.js`, and `frontend/vite.config.d.ts`.

## Verification

- `py -3.11 -m pytest tests/test_web.py tests/test_checkpoint.py tests/test_rebuttal.py -v`: 39 passed, 1 existing Starlette/httpx deprecation warning.
- `npm run build` in `frontend/`: passed; `frontend/dist/index.html` exists.
- `powershell -NoProfile -ExecutionPolicy Bypass -File .\start_web.ps1 -CheckOnly`: passed and printed `React build detected. FastAPI will serve frontend/dist.`

## Sandbox Note

Each verification command initially failed before execution because the Windows sandbox runner returned `CreateProcessAsUserW failed: 5 (access denied)`. The commands were rerun outside the sandbox with approval; results above are from those executions.

## Self-Review

- Scope is limited to `README.md`, `start_web.ps1`, and `.gitignore`.
- The README values and script messages match the task brief verbatim.
- No backend or frontend source was changed.

## Reviewer Fix

- Scoped the TypeScript build-info ignore rule to `frontend/*.tsbuildinfo`.
- `git check-ignore frontend/tsconfig.tsbuildinfo frontend/tsconfig.node.tsbuildinfo`: both paths ignored.
