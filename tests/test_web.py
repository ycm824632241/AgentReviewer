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
