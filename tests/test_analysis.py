from unittest.mock import patch
from test_core import RepoCase
from precedent.storage import Store
from precedent.analysis import check, secrets, redact
from precedent.gitops import Change
from precedent.ingestion import ingest, APIError, GitHub


def seed(store, sha):
    store.set("synthetic", "1")
    store.set("last_ingested", "synthetic fixture")
    for number in (1, 2, 3):
        store.document("pr", {"number": number, "title": "Prevent empty input crash", "body": "Keep the validation guard.", "html_url": "", "created_at": "2026-01-02"})
        store.db.execute("INSERT INTO files VALUES (?,?)", (number, "src/parser.py"))
        store.db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)", (number, number, "src/parser.py", "Please add tests for empty input", "", "2026-01-03"))
    store.db.execute("INSERT INTO commit_pr VALUES (?,1)", (sha,))
    store.document("issue", {"number": 4, "title": "Empty input crashes parser", "body": "Guard required", "html_url": "", "created_at": "2026-01-01"})
    store.db.execute("INSERT INTO pr_issue VALUES (1,4)")
    store.mark(sha)
    store.db.commit()


class AnalysisTests(RepoCase):
    def test_guard_secret_forecast(self):
        self.write("src/parser.py", "def parse(value):\n    if not value:\n        raise ValueError('empty')\n    return value[0]\n")
        sha = self.commit()
        store = Store(self.repo)
        self.addCleanup(store.close)
        seed(store, sha)
        self.write("src/parser.py", "def parse(value):\n    return value[0]\n")
        self.write("config.py", 'api_key = "' + 'AKIA' + 'A' * 16 + '"\n')
        report = check(self.repo, store, self.repo.changes())
        self.assertEqual(report["verdict"], "RED")
        self.assertEqual({f["kind"] for f in report["findings"]}, {"secret", "fence", "forecast"})
        self.assertNotIn('AKIA' + 'A' * 16, str(report))
        self.assertEqual(store.evidence(sha)[0]["kind"], "issue")

    def test_no_history_never_green(self):
        self.write("a.py", "x = 1\n")
        self.commit()
        self.write("a.py", "x = 2\n")
        store = Store(self.repo)
        self.addCleanup(store.close)
        self.assertEqual(check(self.repo, store, self.repo.changes())["verdict"], "YELLOW")

    def test_replacement_guard_yellow(self):
        self.write("src/parser.py", "if not value:\n    raise ValueError('empty')\n")
        sha = self.commit()
        self.write("src/parser.py", "if value is None:\n    raise ValueError('none')\n")
        store = Store(self.repo)
        self.addCleanup(store.close)
        seed(store, sha)
        self.assertEqual(check(self.repo, store, self.repo.changes())["verdict"], "YELLOW")

    def test_scanner_patterns_and_redaction(self):
        cases = ['AKIA' + 'A' * 16, 'ghp_' + 'b' * 36, '-----BEGIN RSA PRIVATE KEY-----', 'password="notarealsecret"']
        for value in cases:
            report = secrets([Change("x", "x", "", [], [(1, value)])])
            self.assertEqual(report[0]["level"], "RED")
            self.assertNotIn(value, redact(value))


class IngestionTests(RepoCase):
    def test_ingestion_associations_and_incremental(self):
        self.write("src/parser.py", "pass\n")
        sha = self.commit()
        store = Store(self.repo)
        self.addCleanup(store.close)
        class Fake:
            calls = 0
            def get(self, path):
                self.calls += 1
                if "/commits/" in path:
                    return {"commit": {"message": "guard"}}
                if "/issues/" in path:
                    return {"number": 4, "title": "crash", "body": "empty input"}
                return {"number": 1, "title": "fix crash", "body": "Fixes #4. See other/repo#99"}
            def pages(self, path):
                self.calls += 1
                if path.endswith("/pulls"):
                    return [{"number": 1}]
                if path.endswith("/files"):
                    return [{"filename": "src/parser.py"}]
                return [{"id": 8, "path": "src/parser.py", "body": "add tests"}]
        api = Fake()
        ingest(self.repo, store, "demo/repo", client=api, progress=lambda x: None)
        self.assertEqual({e["kind"] for e in store.evidence(sha)}, {"pr", "issue", "review"})
        count = api.calls
        ingest(self.repo, store, "demo/repo", client=api, progress=lambda x: None)
        self.assertEqual(api.calls, count)
        self.assertTrue(store.covered(sha))

    def test_network_failure_leaves_incomplete(self):
        self.write("a.py", "pass\n")
        self.commit()
        store = Store(self.repo)
        self.addCleanup(store.close)
        with patch("urllib.request.urlopen", side_effect=OSError("offline")):
            with self.assertRaises(APIError):
                ingest(self.repo, store, "demo/repo", progress=lambda x: None)
        self.assertEqual(store.get("ingestion_status"), "incomplete")
