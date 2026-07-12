# tests/test_web.py
import pytest
from fastapi.testclient import TestClient
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

    def test_upload_txt_returns_thread_id(self):
        r = client.post("/upload", files={"file": ("test.txt", self.PAPER_TXT.encode("utf-8"), "text/plain")})
        assert r.status_code == 200
        body = r.json()
        assert "thread_id" in body
        assert len(body["thread_id"]) == 36  # uuid4
