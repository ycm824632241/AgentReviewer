# AI 论文审稿系统

LangGraph 多审稿人论文审稿 demo，支持 CLI 审稿和 FastAPI Web 界面。Web 流程使用 SQLite checkpointer 保存审稿状态，并支持作者 Rebuttal 后继续二审。

## Web 界面

推荐使用一键开发启动脚本。它会检查 Python/npm，可选安装依赖，分别启动 FastAPI 后端和 Vite 前端，并打开 `http://localhost:5173`：

```powershell
.\start_dev.ps1
```

常用参数：

```powershell
.\start_dev.ps1 -Install
.\start_dev.ps1 -BackendPort 8080
.\start_dev.ps1 -FrontendPort 5174
.\start_dev.ps1 -NoOpen
.\start_dev.ps1 -NoReload
```

也可以手动用两个终端启动前后端：

```powershell
## Terminal 1: backend
.\start_web.ps1
```

In a second terminal:

```powershell
## Terminal 2: frontend
cd frontend
npm install
npm run dev
```

浏览器打开 `http://localhost:5173`。Vite 默认代理到 `http://127.0.0.1:8000`；使用 `start_dev.ps1` 时，`BackendHost` / `BackendPort` 会通过 `VITE_BACKEND_PROXY_TARGET` 覆盖这个目标。

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

### CLI

原有 CLI 入口仍保留：

```bash
py -3.11 -m paper_reviewer.main -f sample_essay.txt --no-rag
```
