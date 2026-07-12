# AI 论文审稿系统

LangGraph 多审稿人论文审稿 demo，支持 CLI 审稿和 FastAPI Web 界面。Web 流程使用 SQLite checkpointer 保存审稿状态，并支持作者 Rebuttal 后继续二审。

## Web 界面（FastAPI）

如需在浏览器中使用审稿系统：

```bash
pip install -r requirements.txt
uvicorn paper_reviewer.web:app --reload
```

浏览器打开 `http://localhost:8000`。

### 使用流程

1. 首页上传 `.txt` 或 `.pdf` 论文。
2. 进度页实时查看审稿节点（SSE）。
3. 结果页查看各审稿人报告、最终分数和编辑决定。
4. 点击“进入 Rebuttal 环节”，选择审稿人并提交逐点回应。
5. 系统基于 checkpointer 使用同一个 `thread_id` 从一审状态继续二审。
6. Rebuttal 最多 2 轮；达到上限后页面隐藏入口，接口也会拒绝继续提交。

### API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 上传论文 |
| POST | `/upload` | 上传论文，返回 `thread_id` |
| GET | `/progress/{thread_id}` | SSE 实时进度 |
| GET | `/result/{thread_id}` | 渲染审稿结果 |
| GET | `/rebuttal/{thread_id}` | Rebuttal 表单 |
| POST | `/rebuttal/{thread_id}` | 提交 Rebuttal 并启动二审 |
| GET | `/history` | 全部审稿 session |

### CLI

原有 CLI 入口仍保留：

```bash
py -3.11 -m paper_reviewer.main -f sample_essay.txt --no-rag
```
