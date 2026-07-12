# paper_reviewer/web.py
"""FastAPI 服务层。路由：upload / progress / result / rebuttal / history。"""
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from paper_reviewer.checkpoint import list_threads

BASE_DIR = os.path.dirname(__file__)
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app = FastAPI(title="AI 论文审稿系统")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse(request, "index.html")


@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    threads = list_threads()
    return templates.TemplateResponse(request, "history.html", context={"threads": threads})
