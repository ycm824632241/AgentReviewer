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
import os
import sqlite3
import threading
from typing import Optional, List
from langgraph.checkpoint.sqlite import SqliteSaver


DEFAULT_DB = os.path.join(os.path.dirname(__file__), "..", "reviewer_memory.db")


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
