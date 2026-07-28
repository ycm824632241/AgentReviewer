# Agent-AI 项目当前进度

日期：2026-07-28

本文档记录当前工作区在 UI 与 RAG/embedding 集成后的状态，方便后续继续开发、回滚排查或交接。

## 当前代码状态

- 当前主工作区位于 `C:\Yechen_project\Agent-AI`，分支为 `main`。
- `main` 已合并较新的 React/Vite UI 与 RAG 稳定性改造。
- 当前主提交：`335d65e merge: adopt React UI and resilient RAG integration`。
- 合并前主工作区内容已保存到备份分支：
  `backup/pre-ui-rag-integration-20260727`。
- 原集成分支：
  `integrate-ui-rag`，提交 `210e585 fix: make RAG chunking and embedding fallback resilient`。
- `.worktrees` 中仍保留过渡工作树，但当前主要修改已经落在主工作区 `main` 上。
- `AgentReviewer-github/` 是旁边的一份独立仓库目录，没有作为主项目的一部分合并。

## 已完成内容

### UI 与后端

- 引入并合并新版 React/Vite 前端，目录为 `frontend/`。
- 后端保留 FastAPI 服务，并提供 `/api/*` JSON 接口。
- 前端开发模式默认通过 `http://127.0.0.1:5173` 访问。
- 后端 API 默认通过 `http://127.0.0.1:8000` 访问。
- 若已构建 `frontend/dist`，后端也可以服务构建后的静态前端。
- 之前出现的“读取设置失败：502”主要原因是后端或前端代理服务没有完整启动；服务启动后 `/api/settings` 已验证可返回 200。

### RAG 与分块

- 已重做论文分块逻辑，使其优先按标题、段落和句子边界切分。
- 当前分块目标大小为约 1000 字符，邻接块保留约 150 字符重叠。
- 每个 chunk 增加了字节上限保护，避免单块内容过大导致 embedding 请求失败。
- 分块过程保证前进，避免因为特殊长段落、长公式或异常文本造成切片停滞。
- 实测 `test2.pdf`：
  - 提取正文约 48,969 字符。
  - 生成 74 个 chunks。
  - chunk 最小约 222 字符，最大约 1000 字符。
  - 相邻 chunk 重叠关系正常。

### Embedding 稳定性

- 之前的问题不是“调用 embedding 模型导致分块失败”，而是分块与建索引流程耦合太紧：
  分块已经产生，但 embedding 阶段失败时，整个 RAG 索引构建被视为失败，表现上像是“分块没生效”。
- 现在将 chunk 生成和 embedding 索引构建做了容错分离。
- embedding 请求失败时，系统会保留已经生成的 chunks，并记录错误类型与检索状态。
- RAG 检索失败时不再退回整篇论文全文，而是使用有边界的确定性 fallback，从 chunks 中选取有限上下文。
- embedding 批处理加入大小限制，降低单次请求过大造成失败的概率。

## 验证结果

已完成的本地验证：

- 后端离线测试通过：`101 passed, 1 deselected, 1 warning`。
- 前端构建通过：`npm run build`。
- 真实 PDF 分块回归测试通过，分段大小和重叠符合预期。
- `/api/settings` 在服务启动后返回 HTTP 200。

未完整覆盖的验证：

- 依赖外部 LLM 或真实 embedding 服务的端到端测试仍需在有效 API 配置下单独运行。
- 当前验证未暴露或记录任何 `.env` 中的密钥内容。

## 当前启动流程

开发模式推荐：

```powershell
.\start_dev.ps1
```

该脚本会启动：

- 后端 FastAPI 服务，默认端口 `8000`。
- 前端 Vite 开发服务，默认端口 `5173`。

访问入口：

- 前端界面：`http://127.0.0.1:5173`
- 后端 API：`http://127.0.0.1:8000`

如果再次看到“读取设置失败：502”，优先检查：

- 后端 `8000` 是否正在监听。
- 前端 `5173` 是否正在监听。
- 前端代理是否能访问 `http://127.0.0.1:8000/api/settings`。

## 当前工作区注意事项

- 当前未提交变化中包含测试运行生成的 `__pycache__` 文件。
- `.env` 属于本地配置和敏感信息，不应提交。
- `frontend/node_modules/` 是依赖安装目录，不应提交。
- `.worktrees/` 中的历史工作树可在确认不再需要后清理，但不建议在未确认前删除。
- `AgentReviewer-github/` 是独立仓库，如需统一代码来源，后续需要单独决定是否删除、归档或同步。

## 建议后续事项

- 在真实 API 配置下跑一次完整论文评审流程，确认 embedding、检索、分析和报告生成端到端可用。
- 视情况清理测试产生的 `__pycache__`，避免干扰 `git status`。
- 明确是否保留 `.worktrees/` 和 `AgentReviewer-github/` 两份历史/旁路代码。
- 若当前 `main` 稳定，可以为本次进度文档单独提交一次文档提交。
