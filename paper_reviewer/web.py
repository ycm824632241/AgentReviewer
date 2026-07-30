# paper_reviewer/web.py
"""FastAPI 服务层。路由：upload / progress / result / rebuttal / history。"""
import asyncio
import json
import os
import uuid

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from paper_reviewer.checkpoint import get_thread_state, list_threads
from paper_reviewer.config import get_env_path

BASE_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")
SETTINGS_ENV_PATH = get_env_path()
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="AgentReviewer")

if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

# ── 全局状态（demo 级，进程内） ──
_paper_store: dict[str, str] = {}      # thread_id → 论文原文
_task_status: dict[str, dict] = {}     # thread_id → {"done": [...], "current": "", "finished": bool, "error": str}
VALID_REBUTTAL_TARGETS = {"eic", "methodology", "domain", "perspective", "devils_advocate", "all"}
REVIEWER_ROLE_TARGETS = {
    "EIC": "eic",
    "Methodology": "methodology",
    "Domain": "domain",
    "Perspective": "perspective",
    "Devil": "devils_advocate",
    "DevilsAdvocate": "devils_advocate",
    "Devil's Advocate": "devils_advocate",
}

SETTINGS_KEYS = {
    "llm": {
        "base_url": "REVIEW_LLM_BASE_URL",
        "api_key": "REVIEW_LLM_API_KEY",
        "model": "REVIEW_LLM_MODEL",
    },
    "embedding": {
        "base_url": "EMBEDDING_BASE_URL",
        "api_key": "EMBEDDING_API_KEY",
        "model": "EMBEDDING_MODEL",
    },
}
LEGACY_SETTINGS_KEYS = {
    "llm": {
        "base_url": "MIMO_BASE_URL",
        "api_key": "MIMO_API_KEY",
        "model": "MIMO_MODEL_DEBATER",
    },
    "embedding": {
        "base_url": "GITEE_BASE_URL",
        "api_key": "GITEE_API_KEY",
        "model": "GITEE_EMBED_MODEL",
    },
}
SETTINGS_DEFAULTS = {
    "REVIEW_LLM_BASE_URL": "https://token-plan-cn.xiaomimimo.com/v1",
    "REVIEW_LLM_MODEL": "mimo-v2.5-pro",
    "EMBEDDING_BASE_URL": "https://ai.gitee.com/v1",
    "EMBEDDING_MODEL": "Qwen3-Embedding-4B",
}


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _release_graph_checkpointer(graph_app) -> None:
    checkpointer = getattr(graph_app, "checkpointer", None)
    if hasattr(checkpointer, "release"):
        checkpointer.release()


def _read_env_file(path: str | None = None) -> dict[str, str]:
    path = path or SETTINGS_ENV_PATH
    values: dict[str, str] = {}
    if not os.path.exists(path):
        return values
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or "=" not in stripped:
                continue
            key, value = stripped.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 4:
        return "*" * len(value)
    return "*" * (len(value) - 4) + value[-4:]


def _settings_payload(values: dict[str, str]) -> dict:
    payload = {}
    for group, keys in SETTINGS_KEYS.items():
        legacy_keys = LEGACY_SETTINGS_KEYS.get(group, {})
        api_key = values.get(keys["api_key"], values.get(legacy_keys.get("api_key", ""), ""))
        payload[group] = {
            "base_url": values.get(
                keys["base_url"],
                values.get(legacy_keys.get("base_url", ""), SETTINGS_DEFAULTS.get(keys["base_url"], "")),
            ),
            "api_key": _mask_secret(api_key),
            "api_key_set": bool(api_key),
            "model": values.get(
                keys["model"],
                values.get(legacy_keys.get("model", ""), SETTINGS_DEFAULTS.get(keys["model"], "")),
            ),
        }
    return payload


def _write_env_updates(updates: dict[str, str], path: str | None = None) -> None:
    path = path or SETTINGS_ENV_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lines = []
    seen = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()

    next_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                next_lines.append(f"{key}={updates[key]}\n")
                seen.add(key)
                continue
        next_lines.append(line)

    for group in SETTINGS_KEYS.values():
        for key in group.values():
            if key in updates and key not in seen:
                next_lines.append(f"{key}={updates[key]}\n")
                seen.add(key)

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(next_lines)


def _settings_updates_from_payload(payload: dict) -> dict[str, str]:
    updates: dict[str, str] = {}
    for group_name, keys in SETTINGS_KEYS.items():
        group = payload.get(group_name, {})
        if not isinstance(group, dict):
            continue
        for field, env_key in keys.items():
            if field not in group:
                continue
            value = str(group[field]).strip()
            if field == "api_key" and not value:
                continue
            updates[env_key] = value
    return updates


def _embedding_settings_changed(updates: dict[str, str], previous: dict[str, str]) -> bool:
    embedding_keys = set(SETTINGS_KEYS["embedding"].values())
    for key in embedding_keys.intersection(updates):
        legacy_key = {
            value: LEGACY_SETTINGS_KEYS["embedding"][field]
            for field, value in SETTINGS_KEYS["embedding"].items()
        }.get(key)
        previous_value = previous.get(key, previous.get(legacy_key, SETTINGS_DEFAULTS.get(key, "")))
        if updates[key] != previous_value:
            return True
    return False


# ── 节点中文名（用于前端展示） ──
NODE_LABELS = {
    "field_analyst": "领域分析",
    "eic": "主编视角评审",
    "methodology": "方法论审稿",
    "domain": "领域专家审稿",
    "perspective": "跨学科审稿",
    "devils_advocate": "魔鬼评审人压力测试",
    "rebuttal_eic": "主编视角二审",
    "rebuttal_methodology": "方法论二审",
    "rebuttal_domain": "领域专家二审",
    "rebuttal_perspective": "跨学科二审",
    "rebuttal_devils_advocate": "魔鬼评审人二审",
    "synthesizer": "编辑综合",
}


ROUND_ONE_PROGRESS_FIELDS = (
    ("field_analyst", "reviewer_configs"),
    ("eic", "eic_report"),
    ("methodology", "methodology_report"),
    ("domain", "domain_report"),
    ("perspective", "perspective_report"),
    ("devils_advocate", "devils_advocate_report"),
)


def _completed_nodes_from_checkpoint(saved: dict | None) -> list[str]:
    """根据已保存 checkpoint 还原历史审稿进度节点。"""
    if not saved:
        return []

    done = [node for node, field in ROUND_ONE_PROGRESS_FIELDS if saved.get(field)]
    if _is_completed_review(saved):
        done.append("synthesizer")
    return done


def _on_node_complete(thread_id: str, node_name: str) -> None:
    """记录某个节点完成；线程安全（CPython GIL 下 dict 操作原子）。"""
    st = _task_status.setdefault(thread_id, {"done": [], "current": ""})
    if node_name not in st["done"]:
        st["done"].append(node_name)
    st["current"] = node_name


def _run_review(thread_id: str, paper_text: str, title: str) -> None:
    """
    在后台线程中运行一审图（含 checkpointer 断点保存）。

    同步函数设计为供 BackgroundTasks 调用：FastAPI 会在独立线程池中运行同步
    后台任务，因此这里可以用同步 LangGraph API（ streamed via graph.stream ）。
    编译使用带 checkpointer 的变体，便于中断恢复和 /history 查询。
    """
    from paper_reviewer.graph import build_review_graph_with_checkpoint
    from paper_reviewer.state import ReviewState

    graph_app = None
    try:
        graph_app = build_review_graph_with_checkpoint()
        initial_state = ReviewState(
            paper=paper_text,
            paper_title=title,
            language="zh",
            rag_index=None,
            primary_discipline="",
            secondary_disciplines=[],
            research_paradigm="",
            methodology_type="",
            target_journal_tier="",
            reviewer_configs=[],
            eic_report=None,
            methodology_report=None,
            domain_report=None,
            perspective_report=None,
            devils_advocate_report=None,
            editorial_decision="",
            consensus_analysis=None,
            dimension_scores=None,
            decision_trace=None,
            revision_roadmap=None,
            synthesized_round=None,
            round_number=1,
            rebuttal_text=None,
            rebuttal_target=None,
            rebuttal_history=[],
        )
        config = {"configurable": {"thread_id": thread_id}}
        for chunk in graph_app.stream(initial_state, config=config):
            # chunk 是 {node_name: output_dict} 的字典
            for node_name in chunk:
                _on_node_complete(thread_id, node_name)
        _task_status.setdefault(thread_id, {})["finished"] = True
    except Exception as e:  # 后台任务异常不能抛给客户端，需记录
        _task_status.setdefault(thread_id, {})["error"] = repr(e)
    finally:
        if graph_app is not None:
            _release_graph_checkpointer(graph_app)


@app.post("/upload")
async def upload(request: Request, file: UploadFile, background_tasks: BackgroundTasks):
    """上传论文（.txt / .pdf），生成 thread_id，后台启动一审。"""
    raw = await file.read()
    text = raw.decode("utf-8") if file.filename.endswith(".txt") else _decode_pdf(raw)
    thread_id = str(uuid.uuid4())
    _paper_store[thread_id] = text
    _task_status[thread_id] = {"done": [], "current": ""}
    background_tasks.add_task(_run_review, thread_id, text, file.filename)
    if _wants_html(request):
        return RedirectResponse(f"/reviews/{thread_id}/progress", status_code=303)
    return {"thread_id": thread_id}


def _decode_pdf(raw: bytes) -> str:
    """极简 PDF 文本抽取（无密码、无 OCR）；失败时退化为空串。"""
    try:
        import PyPDF2, io
        reader = PyPDF2.PdfReader(io.BytesIO(raw))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except Exception:
        return ""


def _result_payload(thread_id: str, saved: dict | None) -> dict:
    st = _task_status.get(thread_id, {})
    round_number = saved.get("round_number", 1) if saved else 1
    paper = (saved or {}).get("paper") or _paper_store.get(thread_id, "")
    rag_diagnostics = None
    if paper:
        from paper_reviewer.graph import get_rag_diagnostics
        rag_diagnostics = get_rag_diagnostics(paper)
    return {
        "thread_id": thread_id,
        "state": saved,
        "progress": (
            {"done": _completed_nodes_from_checkpoint(saved), "finished": True}
            if not st and _is_completed_review(saved)
            else st
        ),
        "locked": round_number >= 2,
        "rag_diagnostics": rag_diagnostics,
    }


def _is_completed_review(saved: dict | None) -> bool:
    """Return whether a checkpoint has synthesis for its current review round."""
    if not saved or not any(
        saved.get(key)
        for key in ("editorial_decision", "dimension_scores", "revision_roadmap", "consensus_analysis")
    ):
        return False

    round_number = saved.get("round_number", 1)
    synthesized_round = saved.get("synthesized_round")
    if round_number <= 1:
        return synthesized_round is None or synthesized_round == 1
    return synthesized_round == round_number


def _rebuttal_reviewers(reviewer_configs: list[dict]) -> list[dict]:
    """Add API-safe rebuttal targets without changing saved reviewer metadata."""
    reviewers = []
    for config in reviewer_configs:
        target = REVIEWER_ROLE_TARGETS.get(config.get("role"))
        reviewers.append({**config, **({"target": target} if target else {})})
    return reviewers


@app.get("/progress/{thread_id}")
async def progress(thread_id: str):
    """SSE 流：实时推送所有已完成的节点 + 最终 finished/error 事件。"""
    async def event_stream():
        if thread_id not in _task_status:
            saved = get_thread_state(thread_id)
            if _is_completed_review(saved):
                yield "data: " + json.dumps({"node": "__all__", "status": "finished"}, ensure_ascii=False) + "\n\n"
            elif saved is None:
                yield "data: " + json.dumps({"node": "__error__", "status": "thread not found"}, ensure_ascii=False) + "\n\n"
            else:
                yield "data: " + json.dumps({"node": "__error__", "status": "thread is not active"}, ensure_ascii=False) + "\n\n"
            return

        prev_done: list = []
        while True:
            st = _task_status.get(thread_id, {})
            done = st.get("done", [])
            for n in [x for x in done if x not in prev_done]:
                yield (
                    "data: "
                    + json.dumps(
                        {"node": n, "label": NODE_LABELS.get(n, n), "status": "done"},
                        ensure_ascii=False,
                    )
                    + "\n\n"
                )
            prev_done = list(done)
            if st.get("finished"):
                yield "data: " + json.dumps({"node": "__all__", "status": "finished"}, ensure_ascii=False) + "\n\n"
                break
            if st.get("error"):
                yield "data: " + json.dumps({"node": "__error__", "status": st["error"]}, ensure_ascii=False) + "\n\n"
                break
            await asyncio.sleep(0.5)
    return StreamingResponse(event_stream(), media_type="text/event-stream")


@app.post("/api/upload")
async def api_upload(file: UploadFile, background_tasks: BackgroundTasks):
    raw = await file.read()
    text = raw.decode("utf-8") if file.filename.endswith(".txt") else _decode_pdf(raw)
    thread_id = str(uuid.uuid4())
    _paper_store[thread_id] = text
    _task_status[thread_id] = {"done": [], "current": ""}
    background_tasks.add_task(_run_review, thread_id, text, file.filename)
    return {"thread_id": thread_id}


@app.get("/api/progress/{thread_id}")
async def api_progress(thread_id: str):
    return await progress(thread_id)


@app.get("/api/result/{thread_id}")
async def api_result(thread_id: str):
    saved = get_thread_state(thread_id)
    if saved is None and thread_id not in _task_status:
        raise HTTPException(status_code=404, detail="thread not found")
    return _result_payload(thread_id, saved)


@app.get("/api/rebuttal/{thread_id}")
async def api_rebuttal_info(thread_id: str):
    saved = get_thread_state(thread_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="thread not found")
    round_number = saved.get("round_number", 1)
    return {
        "thread_id": thread_id,
        "reviewers": _rebuttal_reviewers(saved.get("reviewer_configs", [])),
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


@app.get("/api/settings")
async def api_settings():
    return _settings_payload(_read_env_file())


@app.post("/api/settings")
async def api_update_settings(payload: dict):
    updates = _settings_updates_from_payload(payload)
    previous = _read_env_file()
    _write_env_updates(updates)
    for key, value in updates.items():
        os.environ[key] = value
    if _embedding_settings_changed(updates, previous):
        from paper_reviewer.graph import clear_rag_cache
        clear_rag_cache()
    return _settings_payload(_read_env_file())


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    return templates.TemplateResponse(request, "index.html")


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    threads = list_threads()
    return templates.TemplateResponse(request, "history.html", context={"threads": threads})


@app.get("/reviews/{thread_id}/progress", response_class=HTMLResponse)
async def progress_page(request: Request, thread_id: str):
    return templates.TemplateResponse(
        request,
        "progress.html",
        context={"thread_id": thread_id},
    )


@app.get("/result/{thread_id}", response_class=HTMLResponse)
async def result(request: Request, thread_id: str):
    st = _task_status.get(thread_id, {})
    saved = get_thread_state(thread_id)
    round_number = saved.get("round_number", 1) if saved else 1
    return templates.TemplateResponse(
        request,
        "result.html",
        context={
            "thread_id": thread_id,
            "state": saved,
            "progress": st,
            "locked": round_number >= 2,
            "rag_diagnostics": _result_payload(thread_id, saved).get("rag_diagnostics"),
        },
    )


@app.get("/rebuttal/{thread_id}", response_class=HTMLResponse)
async def rebuttal_form(request: Request, thread_id: str):
    saved = get_thread_state(thread_id)
    if saved is None:
        raise HTTPException(status_code=404, detail="thread not found")
    reviewers = saved.get("reviewer_configs", [])
    round_number = saved.get("round_number", 1)
    return templates.TemplateResponse(
        request,
        "rebuttal_form.html",
        context={
            "thread_id": thread_id,
            "reviewers": reviewers,
            "round_number": round_number,
            "locked": round_number >= 2,
        },
    )


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

    def _run():
        graph_app = None
        try:
            graph_app = build_rebuttal_graph()
            config = {"configurable": {"thread_id": thread_id}}
            inp = {
                "rebuttal_text": text,
                "rebuttal_target": target,
                "round_number": next_round,
            }
            for chunk in graph_app.stream(inp, config=config):
                for node_name in chunk:
                    _on_node_complete(thread_id, node_name)
            _task_status.setdefault(thread_id, {})["finished"] = True
            _task_status[thread_id]["round"] = next_round
        except Exception as e:
            _task_status.setdefault(thread_id, {})["error"] = repr(e)
        finally:
            if graph_app is not None:
                _release_graph_checkpointer(graph_app)

    background_tasks.add_task(_run)
    return {"status": "rebuttal_started", "round": next_round, "thread_id": thread_id}


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


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(status_code=404, detail="not found")
    if os.path.exists(FRONTEND_INDEX):
        return FileResponse(FRONTEND_INDEX)
    raise HTTPException(status_code=404, detail="not found")
