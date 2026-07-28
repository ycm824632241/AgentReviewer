# React + Vite Web UI 改造设计

## 背景

当前项目已经具备 FastAPI + Jinja2 + htmx Web Demo，后端直接渲染上传页、进度页、结果页、Rebuttal 表单和历史记录页。核心审稿能力已经稳定落在 Python 侧，包括 LangGraph 多角色审稿工作流、RAG 检索、SQLite Checkpointer、Rebuttal/二审流程和 CLI 入口。

本次改造目标是在不重写核心审稿流程的前提下，引入 React + Vite 构建更现代的单页审稿控制台。开发阶段采用前后端分离，生产或演示阶段允许 FastAPI 托管前端构建产物，兼顾交互体验与启动便利性。

## 目标

- 使用 React + Vite 构建单页 Web UI，替代现有 Jinja2 页面作为主要浏览器入口。
- 保留 FastAPI + Uvicorn 作为 Python 后端，继续直接调用 LangGraph、RAG 和 SQLite Checkpointer。
- 将现有页面路由补齐为 JSON API，供 React 前端通过 REST API + SSE 调用。
- 开发阶段分别启动前端和后端：Vite 运行在 `localhost:5173`，FastAPI 运行在 `localhost:8000`。
- 生产或演示阶段通过 `npm run build` 生成 `frontend/dist`，再由 FastAPI 托管静态资源。
- 保留 CLI 使用方式，不影响命令行批处理。

## 非目标

- 不把后端替换为 Node.js 或 Express。
- 不重写 LangGraph 审稿图、RAG 检索、LLM 调用和 checkpointer 逻辑。
- 不引入多页面复杂路由，首版聚焦单页审稿控制台。
- 不实现用户登录、多租户、权限系统或多人协作。

## 架构

开发阶段：

```text
React + Vite frontend      http://localhost:5173
        |
        | REST API + SSE
        v
FastAPI backend            http://localhost:8000
        |
        v
LangGraph / RAG / SQLite Checkpointer / LLM API
```

演示阶段：

```text
frontend/dist
        |
        v
FastAPI StaticFiles + API routes
        |
        v
LangGraph / RAG / SQLite Checkpointer / LLM API
```

FastAPI 保持为唯一后端服务。React 只负责浏览器端交互和展示，不直接访问数据库、checkpointer 或 LLM API。

## 后端设计

现有 Jinja2 页面路由保留一段过渡期，但新增 `/api` 前缀的 JSON 接口作为 React 主入口：

```text
POST /api/upload
GET  /api/progress/{thread_id}
GET  /api/result/{thread_id}
GET  /api/rebuttal/{thread_id}
POST /api/rebuttal/{thread_id}
GET  /api/history
```

接口职责：

- `POST /api/upload` 接收 `.txt` 或 `.pdf` 文件，生成 `thread_id`，后台启动一审，返回任务信息。
- `GET /api/progress/{thread_id}` 继续使用 SSE 推送审稿节点状态。
- `GET /api/result/{thread_id}` 返回 checkpointer 中保存的审稿状态、轮次信息和是否允许继续 Rebuttal。
- `GET /api/rebuttal/{thread_id}` 返回可回应的审稿人列表、当前轮次和锁定状态。
- `POST /api/rebuttal/{thread_id}` 接收目标审稿人和逐点回应，基于同一 `thread_id` 启动二审。
- `GET /api/history` 返回历史审稿 session 列表。

后端还需要挂载前端构建产物：

```text
frontend/dist/assets/*  -> StaticFiles
frontend/dist/index.html -> SPA fallback
```

API 路由优先级必须高于 SPA fallback，避免 `/api/*` 被错误返回前端页面。

## 前端设计

React 前端放在 `frontend/` 目录，使用 Vite 初始化。首版为单页应用，不需要 React Router；用组件状态控制上传、进度、结果、Rebuttal 和历史记录面板。

建议组件：

```text
App
UploadPanel
ProgressTimeline
ReviewResult
ReviewerReportCard
RebuttalForm
HistoryPanel
StatusBanner
```

主流程：

1. 用户上传论文。
2. 前端调用 `POST /api/upload` 获取 `thread_id`。
3. 前端连接 `GET /api/progress/{thread_id}` 的 SSE 流，展示节点进度。
4. 收到 finished 事件后调用 `GET /api/result/{thread_id}` 展示审稿结果。
5. 用户提交 Rebuttal 后重新监听同一 `thread_id` 的进度，并展示二审结果。
6. 历史记录面板调用 `GET /api/history`，允许用户打开已有 `thread_id` 的结果。

视觉方向为工作台式 Dashboard：信息密度适中、结构清晰、以审稿进度、审稿人报告和编辑决策为中心，避免营销页式 hero。

## API 数据约定

首版前端直接消费后端现有状态字段，后端做最小包装：

```json
{
  "thread_id": "uuid",
  "state": {},
  "progress": {},
  "locked": false
}
```

SSE 事件沿用当前格式：

```json
{"node": "methodology", "label": "方法论审稿", "status": "done"}
{"node": "__all__", "status": "finished"}
{"node": "__error__", "status": "repr(error)"}
```

如果后续需要更稳定的公开 API，可以再引入 Pydantic response model。首版优先保持改造范围小。

## 启动与部署

开发启动：

```powershell
.\start_web.ps1
cd frontend
npm install
npm run dev
```

Vite 开发服务器通过 proxy 转发 `/api` 和 `/api/progress` 到 `http://localhost:8000`，避免跨域配置复杂化。

演示启动：

```powershell
cd frontend
npm run build
cd ..
.\start_web.ps1
```

此时访问 FastAPI 地址即可加载 React 构建产物和 API。

## 错误处理

- 上传失败时前端显示错误提示，不切换到进度状态。
- SSE 返回 `__error__` 时，进度面板展示后端错误并停止监听。
- 结果接口找不到 `thread_id` 时展示未找到状态，并引导用户返回上传或历史记录。
- Rebuttal 达到轮次上限时禁用提交按钮，并显示二审已完成。
- 前端刷新页面后，如果 URL 或本地状态中有 `thread_id`，可重新拉取结果和历史状态。

## 测试与验证

后端：

- 保留现有 pytest，覆盖上传、结果、Rebuttal、历史记录和 checkpointer 逻辑。
- 新增或调整 API 测试，验证 `/api/*` 返回 JSON，SSE 格式保持兼容。
- 验证 React 构建产物不存在时，FastAPI API 与旧 Jinja 页面仍可工作。

前端：

- 运行 `npm run build` 验证 TypeScript/React 构建通过。
- 手动验证上传、进度、结果、Rebuttal、历史记录五条主路径。
- 在桌面和窄屏宽度检查主要布局不重叠、不溢出。

## 简历表述

前端基于 React + Vite 构建单页审稿控制台，后端基于 FastAPI + Uvicorn 提供论文上传、审稿任务调度、SSE 实时进度推送、Rebuttal 与历史记录 API；开发阶段采用前后端分离架构，生产演示阶段由 FastAPI 托管前端静态资源，兼顾交互体验与部署便利性。
