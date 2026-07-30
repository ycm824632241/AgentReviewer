# paper_reviewer/checkpoint.py
"""Checkpointer 工厂 + thread 查询 helper。

实现说明
--------
SqliteSaver 默认在 ``__init__`` 里建连并长期持有，但在 Windows 上未释放的连
接会锁定 sqlite 文件（即使文件被删也会报 PermissionError）。为避免该问题，
这里把连接改为 *惰性打开*（``_SqliteSaver.conn`` 为 property，首次访问时建
连），并在闲置时不持有文件句柄。

``get_checkpointer`` 返回的是 ``SqliteSaver`` 子类，因此：

- 满足 LangGraph ``ensure_valid_checkpointer`` 的 ``isinstance`` 校验
  （LangGraph >=0.2 在 ``graph.compile(checkpointer=...)`` 时做此检查）；
- 直接复用 SqliteSaver 全部方法（put / get_tuple / list / put_writes 等）
  与序列化能力（serde）。
"""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Optional, List
from langgraph.checkpoint.sqlite import SqliteSaver


DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "reviewer_memory.db")
REVIEW_JOB_COLUMNS = "thread_id, title, status, round_number, done_json, current, error"


class _SqliteSaver(SqliteSaver):
    """惰性建连的 SqliteSaver 子类（闲置 = 无文件句柄）。"""

    def __init__(self, db_path: str):
        self._db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self._conn = None
        # SqliteSaver.__init__ 会建连；我们跳过它、只初始化子类自身依赖的属性，
        # 让连接在首次访问 self.conn 时才建立。
        self.is_setup = False
        self.lock = threading.Lock()
        self.jsonplus_serde = SqliteSaver.serde

    @property
    def conn(self):
        if self._conn is None:
            self._conn = sqlite3.connect(
                self._db_path,
                check_same_thread=False,
            )
            self.setup()
        return self._conn

    @conn.setter
    def conn(self, value):
        self._conn = value

    def release(self) -> None:
        """显式关闭连接；供一次性查询 helper 在返回前释放文件句柄。"""
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self.is_setup = False


def get_checkpointer(db_path: str = DEFAULT_DB) -> SqliteSaver:
    """创建 SqliteSaver（首次访问时才建连，闲置不锁文件）。"""
    return _SqliteSaver(db_path)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _connect_job_db(db_path: str = DEFAULT_DB):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    _ensure_review_jobs(conn)
    return conn


def _ensure_review_jobs(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS review_jobs (
            thread_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            round_number INTEGER NOT NULL DEFAULT 1,
            done_json TEXT NOT NULL DEFAULT '[]',
            current TEXT NOT NULL DEFAULT '',
            error TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.commit()


def _decode_done(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return [item for item in parsed if isinstance(item, str)] if isinstance(parsed, list) else []


def _job_from_row(row) -> dict:
    return {
        "thread_id": row["thread_id"],
        "title": row["title"],
        "status": row["status"],
        "round_number": row["round_number"],
        "done": _decode_done(row["done_json"]),
        "current": row["current"],
        "error": row["error"],
    }


def upsert_review_job(
    thread_id: str,
    title: str = "",
    status: str = "running",
    round_number: int = 1,
    done: list[str] | None = None,
    current: str = "",
    error: str | None = None,
    db_path: str = DEFAULT_DB,
) -> None:
    """Create or replace product-level review task status."""
    now = _utc_now()
    done_json = json.dumps(done or [], ensure_ascii=False)
    with _connect_job_db(db_path) as conn:
        conn.execute(
            """
            INSERT INTO review_jobs (
                thread_id, title, status, round_number, done_json, current, error, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                title = excluded.title,
                status = excluded.status,
                round_number = excluded.round_number,
                done_json = excluded.done_json,
                current = excluded.current,
                error = excluded.error,
                updated_at = excluded.updated_at
            """,
            (thread_id, title, status, round_number, done_json, current, error, now, now),
        )


def get_review_job(thread_id: str, db_path: str = DEFAULT_DB) -> dict | None:
    """Read a product-level review task row."""
    with _connect_job_db(db_path) as conn:
        row = conn.execute(
            f"SELECT {REVIEW_JOB_COLUMNS} FROM review_jobs WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
    return _job_from_row(row) if row else None


def update_review_job_progress(thread_id: str, node_name: str, db_path: str = DEFAULT_DB) -> None:
    """Append a completed node to a review task row."""
    job = get_review_job(thread_id, db_path=db_path)
    done = job["done"] if job else []
    if node_name not in done:
        done.append(node_name)
    upsert_review_job(
        thread_id=thread_id,
        title=(job or {}).get("title", ""),
        status="running",
        round_number=(job or {}).get("round_number", 1),
        done=done,
        current=node_name,
        error=None,
        db_path=db_path,
    )


def finish_review_job(thread_id: str, round_number: int | None = None, db_path: str = DEFAULT_DB) -> None:
    """Mark a review task completed."""
    job = get_review_job(thread_id, db_path=db_path) or {}
    upsert_review_job(
        thread_id=thread_id,
        title=job.get("title", ""),
        status="completed",
        round_number=round_number or job.get("round_number", 1),
        done=job.get("done", []),
        current=job.get("current", ""),
        error=None,
        db_path=db_path,
    )


def fail_review_job(thread_id: str, error: str, db_path: str = DEFAULT_DB) -> None:
    """Mark a review task failed while preserving checkpoint resumability."""
    job = get_review_job(thread_id, db_path=db_path) or {}
    upsert_review_job(
        thread_id=thread_id,
        title=job.get("title", ""),
        status="failed",
        round_number=job.get("round_number", 1),
        done=job.get("done", []),
        current=job.get("current", ""),
        error=error,
        db_path=db_path,
    )


def list_review_jobs(db_path: str = DEFAULT_DB) -> list[dict]:
    """List product-level review task rows, newest first."""
    with _connect_job_db(db_path) as conn:
        rows = conn.execute(
            f"SELECT {REVIEW_JOB_COLUMNS} FROM review_jobs ORDER BY updated_at DESC, created_at DESC"
        ).fetchall()
    return [_job_from_row(row) for row in rows]


def get_thread_state(thread_id: str, db_path: str = DEFAULT_DB) -> Optional[dict]:
    """读取某个 thread 的最新快照（channel_values）；不存在返回 None。"""
    cp = get_checkpointer(db_path)
    try:
        saved = cp.get_tuple({"configurable": {"thread_id": thread_id}})
        # get_tuple 返回 CheckpointTuple（NamedTuple，无 .get 方法），
        # 业务状态保存在 saved.checkpoint["channel_values"]。
        if saved is None:
            return None
        return saved.checkpoint.get("channel_values")
    except Exception:
        return None
    finally:
        cp.release()


def list_threads(db_path: str = DEFAULT_DB) -> List[dict]:
    """列出所有 thread 的 id 和论文标题。"""
    cp = get_checkpointer(db_path)
    try:
        seen = set()
        threads = []
        for tpl in cp.list(None):
            thread_id = tpl.config["configurable"]["thread_id"]
            if thread_id in seen:
                continue
            seen.add(thread_id)
            state = tpl.checkpoint.get("channel_values", {}) if getattr(tpl, "checkpoint", None) else {}
            title = (state.get("paper_title") or "").strip() or "未命名论文"
            threads.append({"thread_id": thread_id, "title": title})
        return threads
    except Exception:
        return []
    finally:
        cp.release()
