# tests/test_web.py
import pytest
from fastapi.testclient import TestClient
import paper_reviewer.web as web
from paper_reviewer.web import app

client = TestClient(app)

class TestSkeleton:
    def test_index_returns_200(self):
        r = client.get("/")
        assert r.status_code == 200
        assert "审稿" in r.text or "Review" in r.text

    def test_history_empty(self):
        r = client.get("/history")
        assert r.status_code == 200


class TestUploadAndProgress:
    PAPER_TXT = """摘要：本研究探讨了人工智能在教育领域的应用。
    方法：采用问卷调查法，收集了200名学生的数据。
    结果：发现AI工具能显著提升学习效率。
    结论：建议在教学中推广AI工具。
    """

    def test_upload_txt_returns_thread_id(self, monkeypatch):
        monkeypatch.setattr(web, "_run_review", lambda *_args, **_kwargs: None)
        r = client.post("/upload", files={"file": ("test.txt", self.PAPER_TXT.encode("utf-8"), "text/plain")})
        assert r.status_code == 200
        body = r.json()
        assert "thread_id" in body
        assert len(body["thread_id"]) == 36  # uuid4


class TestResultAndRebuttal:
    def _upload_without_review(self, monkeypatch):
        monkeypatch.setattr(web, "_run_review", lambda *_args, **_kwargs: None)
        r = client.post(
            "/upload",
            files={"file": ("t.txt", TestUploadAndProgress.PAPER_TXT.encode("utf-8"), "text/plain")},
        )
        assert r.status_code == 200
        return r.json()["thread_id"]

    def test_result_page_returns_200(self, monkeypatch):
        tid = self._upload_without_review(monkeypatch)
        r = client.get(f"/result/{tid}")
        assert r.status_code == 200
        assert tid in r.text

    def test_rebuttal_form_returns_200(self, monkeypatch):
        tid = self._upload_without_review(monkeypatch)
        r = client.get(f"/rebuttal/{tid}")
        assert r.status_code == 200
        assert tid in r.text

    def test_submit_rebuttal_starts_round2(self, monkeypatch):
        class FakeGraph:
            def stream(self, _inp, _config):
                yield {"rebuttal_eic": {}}
                yield {"synthesizer": {}}

        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        import paper_reviewer.graph as graph

        monkeypatch.setattr(graph, "build_rebuttal_graph", lambda: FakeGraph())

        tid = "thread-for-rebuttal"
        web._task_status[tid] = {"done": [], "current": "", "finished": True}
        r = client.post(f"/rebuttal/{tid}", data={"target": "eic", "text": "作者回应"})

        assert r.status_code == 200
        body = r.json()
        assert body == {"status": "rebuttal_started", "round": 2, "thread_id": tid}
        assert web._task_status[tid]["round"] == 2
        assert web._task_status[tid]["finished"] is False
