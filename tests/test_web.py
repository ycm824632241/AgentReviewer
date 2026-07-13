# tests/test_web.py
import asyncio
import json

import pytest
from pathlib import Path
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

    def test_upload_html_redirects_to_progress_page(self, monkeypatch):
        monkeypatch.setattr(web, "_run_review", lambda *_args, **_kwargs: None)
        r = client.post(
            "/upload",
            files={"file": ("test.txt", self.PAPER_TXT.encode("utf-8"), "text/plain")},
            headers={"accept": "text/html"},
            follow_redirects=False,
        )
        assert r.status_code == 303
        assert r.headers["location"].startswith("/reviews/")
        assert r.headers["location"].endswith("/progress")

    def test_run_review_releases_checkpointer(self, monkeypatch):
        class FakeCheckpointer:
            def __init__(self):
                self.released = False

            def release(self):
                self.released = True

        class FakeGraph:
            def __init__(self):
                self.checkpointer = FakeCheckpointer()

            def stream(self, _state, _config):
                yield {"field_analyst": {}}

        fake_graph = FakeGraph()

        import paper_reviewer.graph as graph

        monkeypatch.setattr(graph, "build_review_graph_with_checkpoint", lambda: fake_graph)
        web._run_review("release-thread", self.PAPER_TXT, "test.txt")

        assert fake_graph.checkpointer.released is True


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

    def test_result_page_shows_scores_and_hides_rebuttal_after_round2(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {
                "round_number": 2,
                "editorial_decision": "Minor Revision",
                "dimension_scores": {"originality": 70, "weighted_total": 72.1},
            },
            raising=False,
        )

        r = client.get("/result/locked-thread")

        assert r.status_code == 200
        assert "Minor Revision" in r.text
        assert "originality" in r.text
        assert "72.1" in r.text
        assert "/rebuttal/locked-thread" not in r.text

    def test_rebuttal_form_returns_200(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"round_number": 1, "reviewer_configs": []},
            raising=False,
        )
        tid = "known-thread"
        r = client.get(f"/rebuttal/{tid}")
        assert r.status_code == 200
        assert tid in r.text

    def test_rebuttal_form_rejects_unknown_thread(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.get("/rebuttal/missing")

        assert r.status_code == 404

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

    def test_submit_rebuttal_html_redirects_to_progress_page(self, monkeypatch):
        class FakeGraph:
            def stream(self, _inp, _config):
                yield {"rebuttal_eic": {}}

        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        import paper_reviewer.graph as graph

        monkeypatch.setattr(graph, "build_rebuttal_graph", lambda: FakeGraph())

        r = client.post(
            "/rebuttal/html-thread",
            data={"target": "eic", "text": "作者回应"},
            headers={"accept": "text/html"},
            follow_redirects=False,
        )

        assert r.status_code == 303
        assert r.headers["location"] == "/reviews/html-thread/progress"

    def test_submit_rebuttal_rejects_round3(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 2}, raising=False)

        r = client.post("/rebuttal/already-round2", data={"target": "eic", "text": "再次回应"})

        assert r.status_code == 400
        assert "round limit" in r.text

    def test_submit_rebuttal_rejects_unknown_target(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        r = client.post("/rebuttal/tid", data={"target": "unknown", "text": "作者回应"})

        assert r.status_code == 400
        assert "invalid target" in r.text

    def test_submit_rebuttal_rejects_unknown_thread(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.post("/rebuttal/missing", data={"target": "eic", "text": "作者回应"})

        assert r.status_code == 404

    def test_submit_rebuttal_rejects_in_progress_round2(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)
        tid = "already-running"
        web._task_status[tid] = {"round": 2, "finished": False, "error": None}

        r = client.post(f"/rebuttal/{tid}", data={"target": "eic", "text": "重复提交"})

        assert r.status_code == 409
        assert "already running" in r.text


class TestTemplates:
    def test_progress_endpoint_is_sse(self):
        web._task_status["dummy-tid"] = {"done": [], "finished": True}
        r = client.get("/progress/dummy-tid")
        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_progress_page_renders_sse_template(self):
        r = client.get("/reviews/dummy-tid/progress")
        assert r.status_code == 200
        assert 'sse-connect="/progress/dummy-tid"' in r.text

    def test_progress_template_contains_htmx_sse(self):
        base = Path("paper_reviewer/templates/base.html").read_text(encoding="utf-8")
        tpl = Path("paper_reviewer/templates/progress.html").read_text(encoding="utf-8")
        assert "htmx" in base
        assert "htmx.org@1.9.12" in base
        assert "htmx.org@1.9.12/dist/ext/sse.js" in base
        assert 'hx-ext="sse"' in tpl
        assert 'sse-connect="/progress/{{ thread_id }}"' in tpl
        assert "sse-swap" not in tpl
        assert "hx-sse" not in tpl
        assert "innerHTML" not in tpl

    def test_result_template_shows_reports_and_decision(self):
        tpl = Path("paper_reviewer/templates/result.html").read_text(encoding="utf-8")
        assert "编辑决定" in tpl
        assert "eic_report" in tpl
        assert "revision_roadmap" in tpl

    def test_rebuttal_template_has_target_selector_and_limit_copy(self):
        tpl = Path("paper_reviewer/templates/rebuttal_form.html").read_text(encoding="utf-8")
        assert 'name="target"' in tpl
        assert 'name="text"' in tpl
        assert "role_to_target" in tpl
        assert "已用完" in tpl or "已达" in tpl


class TestApiEndpoints:
    PAPER_TXT = TestUploadAndProgress.PAPER_TXT

    def test_api_upload_txt_returns_thread_id(self, monkeypatch):
        monkeypatch.setattr(web, "_run_review", lambda *_args, **_kwargs: None)

        r = client.post(
            "/api/upload",
            files={"file": ("api.txt", self.PAPER_TXT.encode("utf-8"), "text/plain")},
        )

        assert r.status_code == 200
        assert set(r.json()) == {"thread_id"}
        assert len(r.json()["thread_id"]) == 36

    def test_api_result_returns_json_payload(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"round_number": 2, "editorial_decision": "Accept"},
            raising=False,
        )
        web._task_status["api-result"] = {"done": ["synthesizer"], "finished": True}

        r = client.get("/api/result/api-result")

        assert r.status_code == 200
        assert r.json() == {
            "thread_id": "api-result",
            "state": {"round_number": 2, "editorial_decision": "Accept"},
            "progress": {"done": ["synthesizer"], "finished": True},
            "locked": True,
        }

    def test_api_result_marks_completed_checkpoint_finished_without_task_status(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"editorial_decision": "Accept"},
            raising=False,
        )

        r = client.get("/api/result/checkpoint-completed-result")

        assert r.status_code == 200
        assert r.json()["progress"] == {"done": ["synthesizer"], "finished": True}

    def test_api_result_keeps_legacy_completed_round_one_checkpoint_finished(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"round_number": 1, "editorial_decision": "Accept"},
            raising=False,
        )

        r = client.get("/api/result/legacy-round-one")

        assert r.status_code == 200
        assert r.json()["progress"] == {"done": ["synthesizer"], "finished": True}

    def test_api_result_does_not_complete_interrupted_round_two_checkpoint(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {
                "round_number": 2,
                "editorial_decision": "Accept",
                "dimension_scores": {"weighted_total": 80},
            },
            raising=False,
        )

        r = client.get("/api/result/interrupted-round-two")

        assert r.status_code == 200
        assert r.json()["progress"] == {}

    def test_api_result_rejects_unknown_thread(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.get("/api/result/unknown-result-thread")

        assert r.status_code == 404
        assert r.json()["detail"] == "thread not found"

    def test_api_rebuttal_info_rejects_missing_thread(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.get("/api/rebuttal/missing")

        assert r.status_code == 404
        assert r.json()["detail"] == "thread not found"

    def test_api_rebuttal_info_returns_reviewers(self, monkeypatch):
        saved = {
            "round_number": 1,
            "reviewer_configs": [
                {"role": "EIC", "identity": "主编"},
                {"role": "Methodology", "identity": "方法论专家"},
                {"role": "Domain", "identity": "领域专家"},
                {"role": "Perspective", "identity": "跨学科专家"},
                {"role": "DevilsAdvocate", "identity": "批判学者"},
            ],
        }
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: saved, raising=False)

        r = client.get("/api/rebuttal/api-thread")

        assert r.status_code == 200
        assert r.json() == {
            "thread_id": "api-thread",
            "reviewers": [
                {"role": "EIC", "identity": "主编", "target": "eic"},
                {"role": "Methodology", "identity": "方法论专家", "target": "methodology"},
                {"role": "Domain", "identity": "领域专家", "target": "domain"},
                {"role": "Perspective", "identity": "跨学科专家", "target": "perspective"},
                {"role": "DevilsAdvocate", "identity": "批判学者", "target": "devils_advocate"},
            ],
            "round_number": 1,
            "locked": False,
        }

    def test_api_submit_rebuttal_starts_round2(self, monkeypatch):
        class FakeGraph:
            def stream(self, _inp, _config):
                yield {"rebuttal_eic": {}}

        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        import paper_reviewer.graph as graph

        monkeypatch.setattr(graph, "build_rebuttal_graph", lambda: FakeGraph())

        r = client.post("/api/rebuttal/api-thread", data={"target": "eic", "text": "作者回应"})

        assert r.status_code == 200
        assert r.json() == {"status": "rebuttal_started", "round": 2, "thread_id": "api-thread"}

    def test_api_submit_rebuttal_records_graph_build_error(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: {"round_number": 1}, raising=False)

        import paper_reviewer.graph as graph

        def raise_graph_build_error():
            raise RuntimeError("graph build failed")

        monkeypatch.setattr(graph, "build_rebuttal_graph", raise_graph_build_error)

        r = client.post(
            "/api/rebuttal/graph-build-error",
            data={"target": "eic", "text": "作者回应"},
        )

        assert r.status_code == 200
        assert "graph build failed" in web._task_status["graph-build-error"]["error"]

        retry = client.post(
            "/api/rebuttal/graph-build-error",
            data={"target": "eic", "text": "再次回应"},
        )
        assert retry.status_code != 409

    def test_api_history_returns_threads(self, monkeypatch):
        monkeypatch.setattr(web, "list_threads", lambda: [{"thread_id": "a"}, {"thread_id": "b"}], raising=False)

        r = client.get("/api/history")

        assert r.status_code == 200
        assert r.json() == {"threads": [{"thread_id": "a"}, {"thread_id": "b"}]}

    def test_api_settings_reads_masked_model_config(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "\n".join(
                [
                    "MIMO_BASE_URL=https://llm.example/v1",
                    "MIMO_API_KEY=llm-secret-key",
                    "MIMO_MODEL_DEBATER=mimo-test",
                    "GITEE_BASE_URL=https://embed.example/v1",
                    "GITEE_API_KEY=embed-secret-key",
                    "GITEE_EMBED_MODEL=embed-test",
                ]
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(web, "SETTINGS_ENV_PATH", str(env_file), raising=False)

        r = client.get("/api/settings")

        assert r.status_code == 200
        assert r.json() == {
            "llm": {
                "base_url": "https://llm.example/v1",
                "api_key": "**********-key",
                "api_key_set": True,
                "model": "mimo-test",
            },
            "embedding": {
                "base_url": "https://embed.example/v1",
                "api_key": "************-key",
                "api_key_set": True,
                "model": "embed-test",
            },
        }

    def test_api_settings_writes_supported_model_config(self, monkeypatch, tmp_path):
        env_file = tmp_path / ".env"
        env_file.write_text(
            "UNRELATED=value\nMIMO_API_KEY=old-llm-key\nGITEE_API_KEY=old-embed-key\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(web, "SETTINGS_ENV_PATH", str(env_file), raising=False)

        r = client.post(
            "/api/settings",
            json={
                "llm": {
                    "base_url": "https://new-llm.example/v1",
                    "api_key": "new-llm-key",
                    "model": "new-chat-model",
                },
                "embedding": {
                    "base_url": "https://new-embed.example/v1",
                    "api_key": "",
                    "model": "new-embed-model",
                },
            },
        )

        assert r.status_code == 200
        text = env_file.read_text(encoding="utf-8")
        assert "UNRELATED=value" in text
        assert "MIMO_BASE_URL=https://new-llm.example/v1" in text
        assert "MIMO_API_KEY=new-llm-key" in text
        assert "MIMO_MODEL_DEBATER=new-chat-model" in text
        assert "GITEE_BASE_URL=https://new-embed.example/v1" in text
        assert "GITEE_API_KEY=old-embed-key" in text
        assert "GITEE_EMBED_MODEL=new-embed-model" in text

    def test_api_progress_endpoint_is_sse(self):
        web._task_status["api-progress"] = {"done": [], "finished": True}

        r = client.get("/api/progress/api-progress")

        assert r.status_code == 200
        assert "text/event-stream" in r.headers.get("content-type", "")

    def test_api_progress_unknown_thread_emits_error_and_terminates(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        response = asyncio.run(web.api_progress("missing-progress-thread"))
        event = asyncio.run(asyncio.wait_for(anext(response.body_iterator), timeout=0.1))

        assert json.loads(event.removeprefix("data: ").strip()) == {
            "node": "__error__",
            "status": "thread not found",
        }

    def test_api_progress_completed_checkpoint_emits_finished_without_task_status(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {"dimension_scores": {"weighted_total": 80}},
            raising=False,
        )

        response = asyncio.run(web.api_progress("checkpoint-completed-progress"))
        event = asyncio.run(asyncio.wait_for(anext(response.body_iterator), timeout=0.1))

        assert json.loads(event.removeprefix("data: ").strip()) == {
            "node": "__all__",
            "status": "finished",
        }

    def test_api_progress_interrupted_round_two_checkpoint_emits_inactive_error(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {
                "round_number": 2,
                "editorial_decision": "Accept",
                "dimension_scores": {"weighted_total": 80},
                "synthesized_round": 1,
            },
            raising=False,
        )

        response = asyncio.run(web.api_progress("interrupted-round-two-progress"))
        event = asyncio.run(asyncio.wait_for(anext(response.body_iterator), timeout=0.1))

        assert json.loads(event.removeprefix("data: ").strip()) == {
            "node": "__error__",
            "status": "thread is not active",
        }

    def test_api_progress_completed_round_two_checkpoint_emits_finished(self, monkeypatch):
        monkeypatch.setattr(
            web,
            "get_thread_state",
            lambda _thread_id: {
                "round_number": 2,
                "editorial_decision": "Accept",
                "dimension_scores": {"weighted_total": 80},
                "synthesized_round": 2,
            },
            raising=False,
        )

        response = asyncio.run(web.api_progress("completed-round-two-progress"))
        event = asyncio.run(asyncio.wait_for(anext(response.body_iterator), timeout=0.1))

        assert json.loads(event.removeprefix("data: ").strip()) == {
            "node": "__all__",
            "status": "finished",
        }


class TestReactStaticHosting:
    def test_api_routes_are_not_spa_fallback(self, monkeypatch):
        monkeypatch.setattr(web, "get_thread_state", lambda _thread_id: None, raising=False)

        r = client.get("/api/result/static-missing")

        assert r.status_code == 404
        assert r.headers["content-type"].startswith("application/json")
        assert r.json()["detail"] == "thread not found"

    def test_root_serves_react_build_when_present(self, monkeypatch, tmp_path):
        index = tmp_path / "index.html"
        index.write_text("<main id=\"react-root\">React bundle</main>", encoding="utf-8")
        monkeypatch.setattr(web, "FRONTEND_INDEX", str(index), raising=False)

        r = client.get("/")

        assert r.status_code == 200
        assert "react-root" in r.text

    def test_root_preserves_jinja_index_without_react_build(self, monkeypatch, tmp_path):
        monkeypatch.setattr(web, "FRONTEND_INDEX", str(tmp_path / "missing-index.html"), raising=False)

        r = client.get("/")

        assert r.status_code == 200
        assert "上传并开始审稿" in r.text

    def test_unknown_route_without_dist_returns_404(self, monkeypatch, tmp_path):
        monkeypatch.setattr(web, "FRONTEND_INDEX", str(tmp_path / "missing-index.html"), raising=False)

        r = client.get("/react-only-route")

        assert r.status_code == 404
