# One-Click Dev Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-command development startup script for the React + Vite frontend and FastAPI backend.

**Architecture:** Keep the backend and frontend as two development services. Use a root PowerShell script to perform checks, optionally install dependencies, launch both services in separate PowerShell windows, and open the Vite URL.

**Tech Stack:** PowerShell, FastAPI, uvicorn, React, Vite, npm.

## Global Constraints

- Work only inside `C:\Yechen_project\Agent-AI\.worktrees\react-vite-web-ui`.
- Keep `start_web.ps1` as the backend-only script.
- Do not change API behavior.
- Default browser URL must be `http://localhost:5173`.

---

### Task 1: Add One-Click Startup Script

**Files:**
- Create: `start_dev.ps1`
- Modify: `README.md`

**Interfaces:**
- Consumes: existing `start_web.ps1`, `frontend/package.json`, `frontend/vite.config.ts`
- Produces: `.\start_dev.ps1 [-Install] [-BackendPort <int>] [-FrontendPort <int>] [-NoOpen] [-NoReload]`

- [ ] **Step 1: Add `start_dev.ps1`**

Create a root PowerShell script that validates Python/npm, optionally installs dependencies, starts backend and frontend in separate PowerShell windows, and opens the frontend URL.

- [ ] **Step 2: Update README startup instructions**

Make `.\start_dev.ps1` the recommended development startup path while preserving the manual two-terminal commands and FastAPI static-build demo path.

- [ ] **Step 3: Verify PowerShell syntax**

Run: `powershell -NoProfile -Command "$null = [scriptblock]::Create((Get-Content -Raw .\start_dev.ps1)); 'syntax ok'"`

Expected: `syntax ok`

- [ ] **Step 4: Verify backend startup checks**

Run: `.\start_web.ps1 -CheckOnly`

Expected: dependency checks complete without starting a long-running server.

- [ ] **Step 5: Verify frontend build**

Run in `frontend`: `npm run build`

Expected: TypeScript and Vite build complete successfully.
