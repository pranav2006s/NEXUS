import json
import os
from pathlib import Path
import threading
import time
from unittest.mock import patch
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient
from precedent.web.server import create_app
from precedent.web.state import State
from precedent.storage import Store
from test_core import RepoCase
from test_analysis import seed


class WebTests(RepoCase):
    def setUp(self):
        super().setUp()
        self.write("src/parser.py", "def parse(value):\n    if not value:\n        raise ValueError('empty')\n    return value[0]\n")
        sha = self.commit()
        store = Store(self.repo)
        seed(store, sha)
        store.close()
        self.write("src/parser.py", "def parse(value):\n    return value[0]\n")
        self.write("config.py", 'api_key="' + 'AKIA' + 'A'*16 + '"\n')
        self.token = "test-only-" + "a"*40
        self.app = create_app(roots=[self.path], state_dir=self.path / ".web-state", token=self.token,
                              origins=["http://localhost:5173"], hosts=["testserver"])
        self.client = TestClient(self.app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.client.headers["Authorization"] = "Bearer " + self.token
        response = self.client.post("/api/v1/repositories", json={"path": str(self.path)})
        self.assertEqual(response.status_code, 201, response.text)
        self.repo_id = response.json()["id"]
        self.url = "/api/v1/repositories/" + self.repo_id

    def test_all_five_features_api_and_redaction(self):
        report = self.client.post(self.url + "/check", json={})
        self.assertEqual(report.status_code, 200, report.text)
        self.assertEqual(report.json()["verdict"], "RED")
        self.assertFalse(report.json()["push_allowed"])
        self.assertNotIn("AKIA" + "A"*16, report.text)
        self.assertEqual({f["kind"] for f in report.json()["findings"]}, {"secret", "fence", "forecast"})
        why = self.client.post(self.url + "/why", json={"path": "src/parser.py", "line": 2})
        self.assertEqual(why.status_code, 200, why.text)
        self.assertTrue(why.json()["evidence"])
        message = self.client.post(self.url + "/commit-message").json()
        self.assertTrue(message["message"].startswith("fix("))
        self.assertTrue(self.client.post(self.url + "/secrets").json()["findings"])
        self.assertTrue(self.client.post(self.url + "/forecast").json()["findings"])

    def test_auth_origin_host_and_cors(self):
        self.assertEqual(self.client.get("/health").status_code, 200)
        self.assertEqual(self.client.get(self.url + "/status", headers={"Authorization": "Bearer wrong"}).status_code, 401)
        self.assertEqual(self.client.get(self.url + "/status", headers={"Origin": "https://untrusted.invalid"}).status_code, 403)
        self.assertEqual(self.client.get("/health", headers={"Host": "evil.invalid"}).status_code, 400)
        response = self.client.options(self.url + "/check", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "authorization,content-type"})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["access-control-allow-origin"], "http://localhost:5173")

    def test_validation_never_echoes_submitted_secrets(self):
        value = "actual-sensitive-request-value"
        response = self.client.post(self.url + "/why", json={"path": "src/parser.py", "line": value})
        self.assertEqual(response.status_code, 422)
        self.assertNotIn(value, response.text)
        response = self.client.post(self.url + "/check", content=b"x" * (1024*1024 + 1))
        self.assertEqual(response.status_code, 413)

    def test_roots_path_traversal_and_unknown_id(self):
        response = self.client.post("/api/v1/repositories", json={"path": str(self.path.parent)})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.client.get("/api/v1/repositories/missing/status").status_code, 404)
        self.assertEqual(self.client.post(self.url + "/why", json={"path": "../outside", "line": 1}).status_code, 400)
        self.assertEqual(self.client.post(self.url + "/stage", json={"paths": [".git/config"]}).status_code, 400)

    def test_registration_is_persistent_and_idempotent(self):
        response = self.client.post("/api/v1/repositories", json={"path": str(self.path)})
        self.assertEqual(response.json()["id"], self.repo_id)
        with self.app.state.backend.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM repositories").fetchone()[0], 1)
        self.assertEqual(len(self.client.get("/api/v1/repositories").json()["repositories"]), 1)

    def test_stage_changes_status_and_hook_installation(self):
        (self.path / "new.py").write_text("pass\n")
        response = self.client.post(self.url + "/stage", json={"paths": ["new.py"]})
        self.assertEqual(response.status_code, 200, response.text)
        paths = [r["path"] for r in self.client.get(self.url + "/changes").json()["files"]]
        self.assertIn("new.py", paths)
        self.assertTrue(self.client.get(self.url + "/status").json()["synthetic"])
        response = self.client.post(self.url + "/hooks", json={})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue((self.repo.gitdir / "hooks/pre-push").exists())

    def test_conflicting_and_shared_hooks_preserved(self):
        hook = self.repo.gitdir / "hooks/pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        response = self.client.post(self.url + "/hooks", json={})
        self.assertEqual(response.status_code, 400, response.text)
        response = self.client.post(self.url + "/hooks", json={"chain_existing": True})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(hook.with_name("pre-push.precedent-original").exists())
        self.git("config", "core.hooksPath", str(self.path / "shared-hooks"))
        self.assertEqual(self.client.post(self.url + "/hooks", json={}).status_code, 403)

    def test_commit_range_detects_secret_removed_later(self):
        base = self.repo.head()
        self.commit("fix: unsafe intermediate commit")
        self.write("config.py", "# removed\n")
        self.commit("fix: remove credential")
        response = self.client.post(self.url + "/check", json={"scope": "commits", "base": base})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(any(f["kind"] == "secret" for f in response.json()["findings"]))

    def wait_job(self, job_id):
        for _ in range(100):
            result = self.client.get("/api/v1/jobs/" + job_id).json()
            if result["status"] in ("succeeded", "failed"): return result
            time.sleep(0.01)
        self.fail("Job did not finish")

    def test_background_ingestion_success_failure_and_busy(self):
        entered, release = threading.Event(), threading.Event()
        def fake(*args, **kwargs):
            entered.set(); release.wait(3); return 5
        with patch("precedent.web.server.ingest", side_effect=fake):
            response = self.client.post(self.url + "/ingest", json={"repository": "demo/repo"})
            self.assertEqual(response.status_code, 202, response.text)
            self.assertTrue(entered.wait(2))
            self.assertEqual(self.client.post(self.url + "/check", json={}).status_code, 409)
            release.set()
            result = self.wait_job(response.json()["job_id"])
            self.assertEqual(result["status"], "succeeded")
            self.assertEqual(result["result"]["selected_commits"], 5)
        with patch("precedent.web.server.ingest", side_effect=OSError("private-secret-text")):
            response = self.client.post(self.url + "/ingest", json={"repository": "demo/repo"})
            result = self.wait_job(response.json()["job_id"])
            self.assertEqual(result["status"], "failed")
            self.assertNotIn("private-secret-text", json.dumps(result))
        self.assertEqual(self.client.get("/api/v1/jobs/missing").status_code, 404)

    def test_restarted_job_is_interrupted(self):
        state = self.app.state.backend
        job_id = state.new_job(self.repo_id)
        other = State(self.path / ".web-state")
        try: self.assertEqual(other.job(job_id)["status"], "interrupted")
        finally: other.pool.shutdown()

    def test_openapi_schema_has_routes_and_auth(self):
        schema = self.client.get("/openapi.json").json()
        self.assertIn(self.url.replace(self.repo_id, "{repo_id}") + "/why", schema["paths"])
        self.assertIn("HTTPBearer", schema["components"]["securitySchemes"])
