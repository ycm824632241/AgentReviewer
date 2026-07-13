# React Vite Web UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the primary browser UI with a React + Vite single-page review console while keeping FastAPI as the Python API backend and preserving the existing LangGraph review workflow.

**Architecture:** FastAPI remains the only backend and exposes JSON API endpoints under `/api`. React + Vite lives in `frontend/`, talks to FastAPI through REST API + SSE during development, and can be built into `frontend/dist` for FastAPI static hosting during demos.

**Tech Stack:** Python 3.11, FastAPI, Uvicorn, LangGraph, SQLite Checkpointer, React, Vite, TypeScript, REST API, Server-Sent Events.

## Global Constraints

- Do not replace the backend with Node.js or Express.
- Do not rewrite LangGraph review graphs, RAG retrieval, LLM calls, or checkpointer logic.
- Keep the first React UI as a single-page review console; do not add multi-page routing.
- Keep the CLI path working.
- Development mode uses two services: Vite on `localhost:5173`, FastAPI on `localhost:8000`.
- Demo mode supports `npm run build` followed by FastAPI serving `frontend/dist`.
- API routes must win over SPA fallback routes.
- Keep existing Jinja2 routes working during the transition.

---

## File Structure

- Modify `paper_reviewer/web.py`: add `/api/*` JSON endpoints, keep existing HTML routes, and add optional static hosting for `frontend/dist`.
- Modify `tests/test_web.py`: add API endpoint tests while preserving existing Jinja2 route tests.
- Create `frontend/package.json`: React + Vite scripts and dependencies.
- Create `frontend/index.html`: Vite HTML entry.
- Create `frontend/vite.config.ts`: Vite React plugin and proxy from `/api` to FastAPI.
- Create `frontend/tsconfig.json`, `frontend/tsconfig.node.json`: TypeScript settings.
- Create `frontend/src/main.tsx`: React entrypoint.
- Create `frontend/src/App.tsx`: main single-page workflow state.
- Create `frontend/src/api.ts`: typed REST and SSE helpers.
- Create `frontend/src/types.ts`: frontend API response and review-state types.
- Create `frontend/src/styles.css`: dashboard UI styling.
- Modify `README.md`: document React + Vite development and demo startup commands.
- Modify `start_web.ps1`: mention frontend build availability only if needed; keep backend startup behavior unchanged.

---

### Task 1: Add FastAPI JSON API Endpoints

**Files:**
- Modify: `paper_reviewer/web.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: existing `_run_review(thread_id: str, paper_text: str, title: str) -> None`, `_task_status`, `get_thread_state(thread_id: str) -> dict | None`, `list_threads() -> list[dict]`.
- Produces:
  - `POST /api/upload -> {"thread_id": str}`
  - `GET /api/result/{thread_id} -> {"thread_id": str, "state": dict | None, "progress": dict, "locked": bool}`
  - `GET /api/rebuttal/{thread_id} -> {"thread_id": str, "reviewers": list, "round_number": int, "locked": bool}`
  - `POST /api/rebuttal/{thread_id} -> {"status": "rebuttal_started", "round": int, "thread_id": str}`
  - `GET /api/history -> {"threads": list[dict]}`
  - `GET /api/progress/{thread_id}` SSE stream using the same event format as `/progress/{thread_id}`.

- [ ] **Step 1: Write failing API tests**

Add this class near the end of `tests/test_web.py`:

```python
class TestApiEndpoints:
    PAPER_TXT = TestUploadAndProgress.PAPER_TXT

    def test_api_upload_txt_returns_thread_id(self, monkeypatch):
        monkeypatch.setattr(web, "_run_review", lambda *_args, **_kwargs: None)

        r = client.post(
            "/api/upload",
            files={"file": ("api.txt", self.PAPER_TXT.encode("utf-8"), "text/plain")},
        )

        assert r.status_code == 200
        assert set(r.json()) == {"thread_id"}
        assert len(r.json()["thread_id"]) == 36

    def test_api_result_returns_json_payload(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"round_number": 2, "editorial_decision": "Accept"},
            raising=False,
        )
        web._task_status["api-result"] = {"done": ["synthesizer"], "finished": True}

        r = client.get("/api/result/api-result")

        assert r.status_code == 200
        assert r.json() == {
            "thread_id": "api-result",
            "state": {"round_number": 2, "editorial_decision": "Accept"},
            "progress": {"done": ["synthesizer"], "finished": True},
            "locked": True,
        }

    def test_api_rebuttal_info_rejects_missing_thread(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.get("/api/rebuttal/missing")

        assert r.status_code == 404
        assert r.json()["detail"] == "thread not found"

    def test_api_rebuttal_info_returns_reviewers(self, monkeypatch):
        saved = {
            "round_number": 1,
            "reviewer_configs": [{"role": "methodology", "name": "方法论专家"}],
        }
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: saved, raising=False)

        r = client.get("/api/rebuttal/api-thread")

        assert r.status_code == 200
        assert r.json() == {
            "thread_id": "api-thread",
            "reviewers": [{"role": "methodology", "name": "方法论专家"}],
            "round_number": 1,
            "locked": False,
        }

    def test_api_submit_rebuttal_starts_round2(self, monkeypatch):
        class FakeGraph:
            def stream(self, _inp, _config):
                yield {"rebuttal_eic": {}}

        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        import paper_reviewer.graph as graph

        monkeypatch.setattr(graph, "build_rebuttal_graph", lambda: FakeGraph())

        r = client.post("/api/rebuttal/api-thread", data={"target": "eic", "text": "作者回应"})

        assert r.status_code == 200
        assert r.json() == {"status": "rebuttal_started", "round": 2, "thread_id": "api-thread"}

    def test_api_history_returns_threads(self, monkeypatch):
        monkeypatch.setattr(web, "list_threads", lambda: [{"thread_id": "a"}, {"thread_id": "b"}], raising=False)

        r = client.get("/api/history")

        assert r.status_code == 200
        assert r.json() == {"threads": [{"thread_id": "a"}, {"thread_id": "b"}]}

    def test_api_progress_endpoint_is_sse(self):
        web._task_status["api-progress"] = {"done": [], "finished": True}

        r = client.get("/api/progress/api-progress")

        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")
```

- [ ] **Step 2: Run tests and verify they fail**

Run:

```powershell
pytest tests/test_web.py::TestApiEndpoints -v
```

Expected: tests fail with `404 Not Found` for the new `/api/*` endpoints.

- [ ] **Step 3: Implement API helpers and routes**

In `paper_reviewer/web.py`, add this helper below `_decode_pdf`:

```python
def _result_payload(thread_id: str) -> dict:
    st = _task_status.get(thread_id, {})
    saved = get_thread_state(thread_id)
    round_number = saved.get("round_number", 1) if saved else 1
    return {
        "thread_id": thread_id,
        "state": saved,
        "progress": st,
        "locked": round_number >= 2,
    }
```

Add these routes before the existing HTML page routes:

```python
@app.post("/api/upload")
async def api_upload(file: UploadFile, background_tasks: BackgroundTasks):
    raw = await file.read()
    text = raw.decode("utf-8") if file.filename.endswith(".txt") else _decode_pdf(raw)
    thread_id = str(uuid.uuid4())
    _paper_store[thread_id] = text
    background_tasks.add_task(_run_review, thread_id, text, file.filename)
    return {"thread_id": thread_id}


@app.get("/api/progress/{thread_id}")
async def api_progress(thread_id: str):
    return await progress(thread_id)


@app.get("/api/result/{thread_id}")
async def api_result(thread_id: str):
    return _result_payload(thread_id)


@app.get("/api/rebuttal/{thread_id}")
async def api_rebuttal_info(thread_id: str):
    saved = get_thread_state(thread_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="thread not found")
    round_number = saved.get("round_number", 1)
    return {
        "thread_id": thread_id,
        "reviewers": saved.get("reviewer_configs", []),
        "round_number": round_number,
        "locked": round_number >= 2,
    }


@app.post("/api/rebuttal/{thread_id}")
async def api_submit_rebuttal(
    thread_id: str,
    background_tasks: BackgroundTasks,
    target: str = Form(...),
    text: str = Form(...),
):
    return await _submit_rebuttal_impl(
        thread_id=thread_id,
        background_tasks=background_tasks,
        target=target,
        text=text,
    )


@app.get("/api/history")
async def api_history():
    return {"threads": list_threads()}
```

Refactor the existing HTML rebuttal route by extracting its shared logic. Replace the body of `submit_rebuttal` with a call to `_submit_rebuttal_impl`:

```python
async def _submit_rebuttal_impl(
    thread_id: str,
    background_tasks: BackgroundTasks,
    target: str,
    text: str,
) -> dict:
    if target not in VALID_REBUTTAL_TARGETS:
        raise HTTPException(status_code=400, detail="invalid target")

    saved = get_thread_state(thread_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="thread not found")
    if saved.get("round_number", 1) >= 2:
        raise HTTPException(status_code=400, detail="round limit reached")

    st = _task_status.setdefault(thread_id, {"done": [], "current": ""})
    if st.get("round") == 2 and not st.get("finished") and not st.get("error"):
        raise HTTPException(status_code=409, detail="rebuttal already running")

    next_round = saved.get("round_number", 1) + 1
    st.update({"done": [], "current": "", "finished": False, "error": None, "round": next_round})

    from paper_reviewer.graph import build_rebuttal_graph

    graph_app = build_rebuttal_graph()
    config = {"configurable": {"thread_id": thread_id}}

    def _run():
        inp = {
            "rebuttal_text": text,
            "rebuttal_target": target,
            "round_number": next_round,
        }
        try:
            for chunk in graph_app.stream(inp, config=config):
                for node_name in chunk:
                    _on_node_complete(thread_id, node_name)
            _task_status.setdefault(thread_id, {})["finished"] = True
            _task_status[thread_id]["round"] = next_round
        except Exception as e:
            _task_status.setdefault(thread_id, {})["error"] = repr(e)
        finally:
            _release_graph_checkpointer(graph_app)

    background_tasks.add_task(_run)
    return {"status": "rebuttal_started", "round": next_round, "thread_id": thread_id}
```

Then keep HTML redirect behavior in `submit_rebuttal`:

```python
@app.post("/rebuttal/{thread_id}")
async def submit_rebuttal(
    request: Request,
    thread_id: str,
    background_tasks: BackgroundTasks,
    target: str = Form(...),
    text: str = Form(...),
):
    body = await _submit_rebuttal_impl(
        thread_id=thread_id,
        background_tasks=background_tasks,
        target=target,
        text=text,
    )
    if _wants_html(request):
        return RedirectResponse(f"/reviews/{thread_id}/progress", status_code=303)
    return body
```

- [ ] **Step 4: Run API tests and existing Web tests**

Run:

```powershell
pytest tests/test_web.py -v
```

Expected: all tests in `tests/test_web.py` pass.

- [ ] **Step 5: Commit**

Run:

```powershell
git add paper_reviewer/web.py tests/test_web.py
git commit -m "feat(web): add json api endpoints"
```

---

### Task 2: Add FastAPI Static Hosting for React Build

**Files:**
- Modify: `paper_reviewer/web.py`
- Modify: `tests/test_web.py`

**Interfaces:**
- Consumes: `frontend/dist/index.html` and `frontend/dist/assets`.
- Produces: FastAPI fallback route serving `frontend/dist/index.html` for non-API browser paths when the build exists.

- [ ] **Step 1: Write failing static hosting tests**

Add this class to `tests/test_web.py`:

```python
class TestReactStaticHosting:
    def test_api_routes_are_not_spa_fallback(self):
        r = client.get("/api/result/static-missing")

        assert r.status_code == 200
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["thread_id"] == "static-missing"

    def test_unknown_route_without_dist_returns_404(self):
        r = client.get("/react-only-route")

        assert r.status_code == 404
```

- [ ] **Step 2: Run tests and verify current behavior**

Run:

```powershell
pytest tests/test_web.py::TestReactStaticHosting -v
```

Expected: the API route test passes after Task 1, and the unknown route returns 404 before a React build exists.

- [ ] **Step 3: Add optional static mounting**

In `paper_reviewer/web.py`, update imports:

```python
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
```

Add constants near `BASE_DIR`:

```python
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")
```

After `app = FastAPI(...)`, mount assets only when a build exists:

```python
if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")
```

At the end of the file, after all API and existing HTML routes, add:

```python
@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    raise HTTPException(status_code=404, detail="not found")
```

- [ ] **Step 4: Run Web tests**

Run:

```powershell
pytest tests/test_web.py -v
```

Expected: all Web tests pass, including the existing Jinja2 routes.

- [ ] **Step 5: Commit**

Run:

```powershell
git add paper_reviewer/web.py tests/test_web.py
git commit -m "feat(web): serve react build when available"
```

---

### Task 3: Scaffold React + Vite Frontend

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.node.json`
- Create: `frontend/src/main.tsx`
- Create: `frontend/src/App.tsx`
- Create: `frontend/src/styles.css`
- Create: `frontend/src/types.ts`
- Create: `frontend/src/api.ts`

**Interfaces:**
- Consumes: `/api/upload`, `/api/progress/{thread_id}`, `/api/result/{thread_id}`, `/api/rebuttal/{thread_id}`, `/api/history`.
- Produces: `npm run dev` and `npm run build` scripts.

- [ ] **Step 1: Create frontend package files**

Create `frontend/package.json`:

```json
{
  "name": "ai-paper-reviewer-frontend",
  "private": true,
  "version": "0.1.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "@vitejs/plugin-react": "^4.3.0",
    "vite": "^5.4.0",
    "typescript": "^5.5.0",
    "react": "^18.3.1",
    "react-dom": "^18.3.1"
  },
  "devDependencies": {}
}
```

Create `frontend/index.html`:

```html
<!doctype html>
<html lang="zh-CN">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>AI 论文审稿系统</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Create `frontend/vite.config.ts`:

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
```

Create `frontend/tsconfig.json`:

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["DOM", "DOM.Iterable", "ES2020"],
    "allowJs": false,
    "skipLibCheck": true,
    "esModuleInterop": true,
    "allowSyntheticDefaultImports": true,
    "strict": true,
    "forceConsistentCasingInFileNames": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx"
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

Create `frontend/tsconfig.node.json`:

```json
{
  "compilerOptions": {
    "composite": true,
    "module": "ESNext",
    "moduleResolution": "Node",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 2: Create minimal React app**

Create `frontend/src/main.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root") as HTMLElement).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

Create `frontend/src/App.tsx`:

```tsx
export default function App() {
  return (
    <main className="app-shell">
      <section className="hero-panel">
        <p className="eyebrow">LangGraph Peer Review Agent</p>
        <h1>AI 论文审稿控制台</h1>
        <p className="subtitle">上传论文，查看多角色审稿进度，并在同一 thread_id 下完成 Rebuttal 与二审。</p>
      </section>
    </main>
  );
}
```

Create `frontend/src/styles.css`:

```css
:root {
  font-family: Inter, "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #17202a;
  background: #f4f7fb;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
}

button,
input,
textarea,
select {
  font: inherit;
}

.app-shell {
  min-height: 100vh;
  padding: 32px;
}

.hero-panel {
  max-width: 1120px;
  margin: 0 auto;
}

.eyebrow {
  margin: 0 0 8px;
  color: #496173;
  font-size: 13px;
  text-transform: uppercase;
}

h1 {
  margin: 0;
  font-size: 34px;
  line-height: 1.15;
}

.subtitle {
  max-width: 720px;
  color: #52616d;
  line-height: 1.7;
}
```

Create `frontend/src/types.ts`:

```ts
export type ProgressEvent = {
  node: string;
  label?: string;
  status: string;
};

export type ReviewResultResponse = {
  thread_id: string;
  state: Record<string, unknown> | null;
  progress: Record<string, unknown>;
  locked: boolean;
};
```

Create `frontend/src/api.ts`:

```ts
import type { ProgressEvent, ReviewResultResponse } from "./types";

export async function uploadPaper(file: File): Promise<{ thread_id: string }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/api/upload", { method: "POST", body: form });
  if (!response.ok) {
    throw new Error(`上传失败：${response.status}`);
  }
  return response.json();
}

export async function fetchResult(threadId: string): Promise<ReviewResultResponse> {
  const response = await fetch(`/api/result/${threadId}`);
  if (!response.ok) {
    throw new Error(`结果读取失败：${response.status}`);
  }
  return response.json();
}

export function openProgressStream(threadId: string, onEvent: (event: ProgressEvent) => void): EventSource {
  const source = new EventSource(`/api/progress/${threadId}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  return source;
}
```

- [ ] **Step 3: Install dependencies**

Run:

```powershell
cd frontend
npm install
```

Expected: `frontend/package-lock.json` is created and dependencies install successfully.

- [ ] **Step 4: Build frontend**

Run:

```powershell
cd frontend
npm run build
```

Expected: `dist` is generated and the command exits with code 0.

- [ ] **Step 5: Commit**

Run:

```powershell
git add frontend
git commit -m "feat(frontend): scaffold react vite app"
```

---

### Task 4: Implement React Review Workflow

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/styles.css`

**Interfaces:**
- Consumes: API helpers from Task 3.
- Produces: A single-page workflow covering upload, SSE progress, result rendering, Rebuttal submission, and history loading.

- [ ] **Step 1: Extend frontend types**

Replace `frontend/src/types.ts` with:

```ts
export type ProgressEvent = {
  node: string;
  label?: string;
  status: string;
};

export type ReviewerConfig = {
  role?: string;
  name?: string;
  [key: string]: unknown;
};

export type ReviewState = {
  paper_title?: string;
  round_number?: number;
  reviewer_configs?: ReviewerConfig[];
  editorial_decision?: string;
  eic_report?: unknown;
  methodology_report?: unknown;
  domain_report?: unknown;
  perspective_report?: unknown;
  devils_advocate_report?: unknown;
  consensus_analysis?: unknown;
  dimension_scores?: Record<string, number>;
  revision_roadmap?: unknown;
  [key: string]: unknown;
};

export type ReviewResultResponse = {
  thread_id: string;
  state: ReviewState | null;
  progress: Record<string, unknown>;
  locked: boolean;
};

export type RebuttalInfoResponse = {
  thread_id: string;
  reviewers: ReviewerConfig[];
  round_number: number;
  locked: boolean;
};

export type HistoryResponse = {
  threads: Array<{ thread_id: string }>;
};
```

- [ ] **Step 2: Extend API client**

Replace `frontend/src/api.ts` with:

```ts
import type { HistoryResponse, ProgressEvent, RebuttalInfoResponse, ReviewResultResponse } from "./types";

async function readJson<T>(response: Response, action: string): Promise<T> {
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${action}失败：${response.status} ${detail}`);
  }
  return response.json();
}

export async function uploadPaper(file: File): Promise<{ thread_id: string }> {
  const form = new FormData();
  form.append("file", file);
  return readJson(await fetch("/api/upload", { method: "POST", body: form }), "上传");
}

export async function fetchResult(threadId: string): Promise<ReviewResultResponse> {
  return readJson(await fetch(`/api/result/${threadId}`), "读取结果");
}

export async function fetchRebuttalInfo(threadId: string): Promise<RebuttalInfoResponse> {
  return readJson(await fetch(`/api/rebuttal/${threadId}`), "读取 Rebuttal 信息");
}

export async function submitRebuttal(threadId: string, target: string, text: string): Promise<{ status: string; round: number; thread_id: string }> {
  const form = new FormData();
  form.append("target", target);
  form.append("text", text);
  return readJson(await fetch(`/api/rebuttal/${threadId}`, { method: "POST", body: form }), "提交 Rebuttal");
}

export async function fetchHistory(): Promise<HistoryResponse> {
  return readJson(await fetch("/api/history"), "读取历史记录");
}

export function openProgressStream(threadId: string, onEvent: (event: ProgressEvent) => void): EventSource {
  const source = new EventSource(`/api/progress/${threadId}`);
  source.onmessage = (message) => onEvent(JSON.parse(message.data));
  return source;
}
```

- [ ] **Step 3: Implement single-page workflow**

Replace `frontend/src/App.tsx` with:

```tsx
import { useEffect, useMemo, useState } from "react";
import { fetchHistory, fetchResult, fetchRebuttalInfo, openProgressStream, submitRebuttal, uploadPaper } from "./api";
import type { ProgressEvent, RebuttalInfoResponse, ReviewResultResponse, ReviewState } from "./types";

const reviewerReports: Array<[keyof ReviewState, string]> = [
  ["eic_report", "Editor-in-Chief"],
  ["methodology_report", "方法论专家"],
  ["domain_report", "领域专家"],
  ["perspective_report", "跨学科视角"],
  ["devils_advocate_report", "Devil's Advocate"]
];

function renderValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "暂无";
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [threadId, setThreadId] = useState("");
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [result, setResult] = useState<ReviewResultResponse | null>(null);
  const [rebuttalInfo, setRebuttalInfo] = useState<RebuttalInfoResponse | null>(null);
  const [history, setHistory] = useState<Array<{ thread_id: string }>>([]);
  const [target, setTarget] = useState("all");
  const [rebuttalText, setRebuttalText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const finished = events.some((event) => event.node === "__all__");
  const state = result?.state;

  const progressLabel = useMemo(() => {
    if (!threadId) return "等待上传";
    if (finished) return "审稿完成";
    return "审稿进行中";
  }, [finished, threadId]);

  async function refreshHistory() {
    const data = await fetchHistory();
    setHistory(data.threads);
  }

  async function loadResult(id: string) {
    const data = await fetchResult(id);
    setResult(data);
    if (data.state) {
      const info = await fetchRebuttalInfo(id).catch(() => null);
      setRebuttalInfo(info);
    }
  }

  function listenProgress(id: string) {
    const source = openProgressStream(id, async (event) => {
      setEvents((prev) => [...prev, event]);
      if (event.node === "__error__") {
        setError(event.status);
        source.close();
      }
      if (event.node === "__all__") {
        source.close();
        await loadResult(id);
        await refreshHistory();
      }
    });
  }

  async function handleUpload() {
    if (!file) {
      setError("请选择 .txt 或 .pdf 文件");
      return;
    }
    setBusy(true);
    setError("");
    setEvents([]);
    setResult(null);
    try {
      const data = await uploadPaper(file);
      setThreadId(data.thread_id);
      listenProgress(data.thread_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "上传失败");
    } finally {
      setBusy(false);
    }
  }

  async function handleSubmitRebuttal() {
    if (!threadId || !rebuttalText.trim()) {
      setError("请填写 Rebuttal 内容");
      return;
    }
    setBusy(true);
    setError("");
    setEvents([]);
    try {
      await submitRebuttal(threadId, target, rebuttalText);
      setRebuttalText("");
      listenProgress(threadId);
    } catch (err) {
      setError(err instanceof Error ? err.message : "提交失败");
    } finally {
      setBusy(false);
    }
  }

  async function openHistory(id: string) {
    setThreadId(id);
    setEvents([]);
    setError("");
    await loadResult(id);
  }

  useEffect(() => {
    refreshHistory().catch(() => setHistory([]));
  }, []);

  return (
    <main className="app-shell">
      <header className="topbar">
        <div>
          <p className="eyebrow">LangGraph Peer Review Agent</p>
          <h1>AI 论文审稿控制台</h1>
        </div>
        <span className="status-pill">{progressLabel}</span>
      </header>

      {error && <div className="error-banner">{error}</div>}

      <section className="layout-grid">
        <div className="main-column">
          <section className="panel">
            <h2>论文上传</h2>
            <div className="upload-row">
              <input type="file" accept=".txt,.pdf" onChange={(event) => setFile(event.target.files?.[0] ?? null)} />
              <button onClick={handleUpload} disabled={busy}>{busy ? "处理中" : "开始审稿"}</button>
            </div>
            {threadId && <p className="muted">thread_id: {threadId}</p>}
          </section>

          <section className="panel">
            <h2>审稿进度</h2>
            <ol className="timeline">
              {events.filter((event) => !event.node.startsWith("__")).map((event, index) => (
                <li key={`${event.node}-${index}`}>
                  <span>{event.label ?? event.node}</span>
                  <small>{event.status}</small>
                </li>
              ))}
            </ol>
            {events.length === 0 && <p className="muted">上传论文后将显示实时节点进度。</p>}
          </section>

          {result && (
            <section className="panel">
              <h2>编辑决定</h2>
              <p className="decision">{renderValue(state?.editorial_decision)}</p>
              <pre>{renderValue(state?.dimension_scores)}</pre>
            </section>
          )}

          {result && (
            <section className="report-grid">
              {reviewerReports.map(([key, label]) => (
                <article className="report-card" key={key}>
                  <h3>{label}</h3>
                  <pre>{renderValue(state?.[key])}</pre>
                </article>
              ))}
            </section>
          )}
        </div>

        <aside className="side-column">
          <section className="panel">
            <h2>Rebuttal</h2>
            <select value={target} onChange={(event) => setTarget(event.target.value)} disabled={result?.locked}>
              <option value="all">全部审稿人</option>
              {(rebuttalInfo?.reviewers ?? []).map((reviewer) => (
                <option key={String(reviewer.role)} value={String(reviewer.role)}>{reviewer.name ?? reviewer.role}</option>
              ))}
            </select>
            <textarea value={rebuttalText} onChange={(event) => setRebuttalText(event.target.value)} disabled={result?.locked} rows={8} />
            <button onClick={handleSubmitRebuttal} disabled={busy || !result || result.locked}>
              {result?.locked ? "二审已完成" : "提交 Rebuttal"}
            </button>
          </section>

          <section className="panel">
            <h2>历史记录</h2>
            <div className="history-list">
              {history.map((item) => (
                <button key={item.thread_id} onClick={() => openHistory(item.thread_id)}>{item.thread_id}</button>
              ))}
            </div>
            {history.length === 0 && <p className="muted">暂无历史记录。</p>}
          </section>
        </aside>
      </section>
    </main>
  );
}
```

- [ ] **Step 4: Replace CSS with dashboard styling**

Replace `frontend/src/styles.css` with:

```css
:root {
  font-family: Inter, "Segoe UI", "Microsoft YaHei", system-ui, sans-serif;
  color: #18242f;
  background: #f3f6fa;
}

* {
  box-sizing: border-box;
}

body {
  margin: 0;
  min-width: 320px;
}

button,
input,
textarea,
select {
  font: inherit;
}

button {
  border: 0;
  border-radius: 8px;
  padding: 10px 14px;
  color: #fff;
  background: #235789;
  cursor: pointer;
}

button:disabled {
  cursor: not-allowed;
  opacity: 0.55;
}

input,
textarea,
select {
  width: 100%;
  border: 1px solid #d6dee6;
  border-radius: 8px;
  padding: 10px 12px;
  color: #18242f;
  background: #fff;
}

textarea {
  resize: vertical;
}

pre {
  white-space: pre-wrap;
  word-break: break-word;
  color: #344452;
  font-family: "Cascadia Mono", Consolas, monospace;
  font-size: 13px;
  line-height: 1.55;
}

.app-shell {
  max-width: 1320px;
  margin: 0 auto;
  padding: 28px;
}

.topbar {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.eyebrow {
  margin: 0 0 8px;
  color: #587084;
  font-size: 13px;
  text-transform: uppercase;
}

h1,
h2,
h3 {
  margin: 0;
  line-height: 1.2;
}

h1 {
  font-size: 32px;
}

h2 {
  font-size: 18px;
}

h3 {
  font-size: 16px;
}

.status-pill {
  border-radius: 999px;
  padding: 8px 12px;
  color: #16413c;
  background: #dff3ee;
  font-size: 13px;
  white-space: nowrap;
}

.error-banner {
  margin-bottom: 16px;
  border: 1px solid #f0b8b8;
  border-radius: 8px;
  padding: 12px;
  color: #7f1d1d;
  background: #fff1f1;
}

.layout-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 340px;
  gap: 18px;
}

.main-column,
.side-column {
  display: grid;
  gap: 18px;
  align-content: start;
}

.panel,
.report-card {
  border: 1px solid #dde5ee;
  border-radius: 8px;
  padding: 18px;
  background: #fff;
  box-shadow: 0 10px 30px rgba(31, 46, 61, 0.06);
}

.upload-row {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  margin-top: 14px;
}

.muted {
  color: #6b7c8a;
}

.timeline {
  display: grid;
  gap: 10px;
  margin: 16px 0 0;
  padding: 0;
  list-style: none;
}

.timeline li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-left: 3px solid #2d7d78;
  padding: 10px 12px;
  background: #f6fbfa;
}

.decision {
  margin: 14px 0;
  font-size: 20px;
  font-weight: 700;
}

.report-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
}

.report-card {
  min-width: 0;
}

.side-column .panel {
  display: grid;
  gap: 12px;
}

.history-list {
  display: grid;
  gap: 8px;
}

.history-list button {
  width: 100%;
  color: #24445c;
  background: #edf3f8;
  text-align: left;
  overflow-wrap: anywhere;
}

@media (max-width: 920px) {
  .layout-grid,
  .report-grid,
  .upload-row {
    grid-template-columns: 1fr;
  }

  .topbar {
    display: grid;
  }
}
```

- [ ] **Step 5: Build frontend**

Run:

```powershell
cd frontend
npm run build
```

Expected: TypeScript and Vite build complete without errors.

- [ ] **Step 6: Commit**

Run:

```powershell
git add frontend/src
git commit -m "feat(frontend): implement review console workflow"
```

---

### Task 5: Document Startup and Verify End-to-End

**Files:**
- Modify: `README.md`
- Modify: `start_web.ps1`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: backend API from Tasks 1-2 and frontend build from Tasks 3-4.
- Produces: documented two-service dev startup and one-service demo startup.

- [ ] **Step 1: Update README startup section**

Replace the Web section in `README.md` with:

````markdown
## Web 界面

开发模式采用前后端分离：

```powershell
.\start_web.ps1
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。Vite 会把 `/api` 请求代理到 `http://127.0.0.1:8000`。

演示模式可以先构建前端，再由 FastAPI 托管静态文件：

```powershell
cd frontend
npm run build
cd ..
.\start_web.ps1
```

浏览器打开 `http://localhost:8000`。

后端常用参数：

```powershell
.\start_web.ps1 -Install
.\start_web.ps1 -Port 8080
.\start_web.ps1 -NoReload
.\start_web.ps1 -CheckOnly
```
````

- [ ] **Step 2: Add a frontend build hint without changing backend startup behavior**

Add this message before `& $PythonExe @PythonArgs @UvicornArgs` in `start_web.ps1`:

```powershell
$FrontendDist = Join-Path $ProjectRoot "frontend\dist\index.html"
if (Test-Path $FrontendDist) {
    Write-Host "React build detected. FastAPI will serve frontend/dist."
} else {
    Write-Host "React build not found. Use frontend npm run dev for the React UI during development."
}
```

- [ ] **Step 3: Run backend tests**

Run:

```powershell
pytest tests/test_web.py tests/test_checkpoint.py tests/test_rebuttal.py -v
```

Expected: all selected tests pass.

- [ ] **Step 4: Run frontend build**

Run:

```powershell
cd frontend
npm run build
```

Expected: build exits with code 0 and `frontend/dist/index.html` exists.

- [ ] **Step 5: Smoke test static hosting**

Run:

```powershell
.\start_web.ps1 -CheckOnly
```

Expected: runtime dependency check passes. If a frontend build exists, the script prints that FastAPI will serve `frontend/dist`.

- [ ] **Step 6: Commit**

Run:

```powershell
git add README.md start_web.ps1
git commit -m "docs: document react vite startup"
```

---

## Self-Review

- Spec coverage: Task 1 covers JSON API conversion; Task 2 covers FastAPI static hosting and API priority; Tasks 3-4 cover React + Vite single-page UI; Task 5 covers startup, build, and verification. CLI preservation is covered by avoiding changes to `paper_reviewer/main.py`.
- Placeholder scan: no task relies on unspecified route names, file names, command names, or deferred behavior.
- Type consistency: API response shapes in Task 1 match frontend types and API helpers in Tasks 3-4.
