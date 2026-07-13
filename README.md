# AgentReviewer

AgentReviewer 是一个基于 LangGraph 的多角色 AI 论文审稿系统，用于模拟学术同行评审流程。系统会为一篇论文并行生成多位审稿人的结构化评审意见，并由编辑综合形成最终决定、评分和修改建议。

项目同时提供 FastAPI 后端、React + Vite 前端和 CLI 使用方式，适合用于 AI Agent 工作流、RAG 长文处理、多智能体协作评审和 Web Demo 展示。

## 核心能力

- 基于 LangGraph 编排多阶段审稿流程，串联领域分析、五类审稿人并行评审、编辑综合决策和 Rebuttal 二审。
- 引入 Editor-in-Chief、方法论专家、领域专家、跨学科视角审稿人、Devil's Advocate 五类角色，从不同角度生成结构化意见。
- 使用 RAG 向量检索对长论文进行分块索引，并为不同审稿角色动态检索相关段落，降低长文直接输入带来的 token 压力。
- 使用 SQLite checkpointer 保存 LangGraph 状态，支持基于同一 `thread_id` 从一审继续进入 Rebuttal / 二审流程。
- 提供 React + Vite 前端和 FastAPI API，支持论文上传、SSE 实时进度、审稿结果展示、Rebuttal 表单和历史记录查看。

## 配置

复制环境变量示例，并填写 LLM 与 Embedding API 配置：

```powershell
Copy-Item .env.example .env
```

需要配置的核心变量：

- `REVIEW_LLM_BASE_URL` / `REVIEW_LLM_API_KEY` / `REVIEW_LLM_MODEL`：审稿 LLM
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`：RAG Embedding 模型

变量名保持 provider-neutral：可以接入任意 OpenAI-compatible Chat / Embedding API。

### 应该使用什么凭证？

你需要准备两类模型 API 凭证：

1. 审稿 LLM 凭证

   用于生成领域分析、审稿人意见、编辑综合决定和 Rebuttal 二审意见。填写：

   ```env
   REVIEW_LLM_BASE_URL=https://your-llm-provider.example/v1
   REVIEW_LLM_API_KEY=your-llm-api-key
   REVIEW_LLM_MODEL=your-chat-model
   ```

2. Embedding 模型凭证

   用于 RAG 分块索引和语义检索。填写：

   ```env
   EMBEDDING_BASE_URL=https://your-embedding-provider.example/v1
   EMBEDDING_API_KEY=your-embedding-api-key
   EMBEDDING_MODEL=your-embedding-model
   ```

这两类凭证可以来自同一个服务商，也可以来自不同服务商。只要 API 兼容 OpenAI 的 Chat Completions / Embeddings 接口即可。

不要把真实 `.env` 提交到 GitHub；仓库只应保留 `.env.example`。

## Web 界面

推荐使用一键开发启动脚本。它会分别启动 FastAPI 后端和 Vite 前端：

```powershell
.\start_dev.ps1
```

第一次运行或依赖缺失时，可以加 `-Install`：

```powershell
.\start_dev.ps1 -Install
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

浏览器打开 `http://localhost:5173`。Vite 默认代理到 `http://127.0.0.1:8000`。

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
