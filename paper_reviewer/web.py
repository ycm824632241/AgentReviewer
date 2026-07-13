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

BASE_DIR = os.path.dirname(__file__)
PROJECT_ROOT = os.path.abspath(os.path.join(BASE_DIR, ".."))
FRONTEND_DIST = os.path.join(PROJECT_ROOT, "frontend", "dist")
FRONTEND_INDEX = os.path.join(FRONTEND_DIST, "index.html")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="AI 论文审稿系统")

if os.path.isdir(os.path.join(FRONTEND_DIST, "assets")):
    app.mount("/assets", StaticFiles(directory=os.path.join(FRONTEND_DIST, "assets")), name="assets")

# ── 全局状态（demo 级，进程内） ──
_paper_store: dict[str, str] = {}      # thread_id → 论文原文
_task_status: dict[str, dict] = {}     # thread_id → {"done": [...], "current": "", "finished": bool, "error": str}
VALID_REBUTTAL_TARGETS = {"eic", "methodology", "domain", "perspective", "devils_advocate", "all"}


def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept


def _release_graph_checkpointer(graph_app) -> None:
    checkpointer = getattr(graph_app, "checkpointer", None)
    if hasattr(checkpointer, "release"):
        checkpointer.release()


# ── 节点中文名（用于前端展示） ──
NODE_LABELS = {
    "field_analyst": "领域分析",
    "eic": "EIC 审稿",
    "methodology": "方法论审稿",
    "domain": "领域专家审稿",
    "perspective": "跨学科审稿",
    "devils_advocate": "魔鬼代言人挑战",
    "rebuttal_eic": "EIC 二审",
    "rebuttal_methodology": "方法论二审",
    "rebuttal_domain": "领域专家二审",
    "rebuttal_perspective": "跨学科二审",
    "rebuttal_devils_advocate": "魔鬼代言人二审",
    "synthesizer": "编辑综合",
}


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
            revision_roadmap=None,
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


@app.get("/progress/{thread_id}")
async def progress(thread_id: str):
    """SSE 流：实时推送所有已完成的节点 + 最终 finished/error 事件。"""
    async def event_stream():
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


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
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
