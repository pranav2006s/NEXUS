import io
import json
import subprocess
import urllib.error
from unittest.mock import patch
from test_core import RepoCase
from test_analysis import seed
from precedent.storage import Store
from precedent.ingestion import GitHub, APIError
from precedent.analysis import check
from precedent.gitops import GitError


class EdgeTests(RepoCase):
    def test_binary_is_incomplete(self):
        (self.path / "binary.dat").write_bytes(b"\0\1\2")
        self.git("add", "binary.dat")
        store = Store(self.repo)
        self.addCleanup(store.close)
        report = check(self.repo, store, self.repo.changes())
        self.assertEqual(report["verdict"], "YELLOW")
        self.assertTrue(any("Binary" in f["message"] for f in report["findings"]))

    def test_empty_changes_and_completed_cache_green(self):
        self.write("a.py", "pass\n")
        sha = self.commit()
        store = Store(self.repo)
        self.addCleanup(store.close)
        seed(store, sha)
        self.assertEqual(check(self.repo, store, self.repo.changes())["verdict"], "GREEN")

    def test_ref_deletion_and_malformed_stdin(self):
        self.write("a", "x")
        sha = self.commit()
        self.assertEqual(self.repo.outgoing(f"(delete) {'0'*40} refs/heads/x {sha}", "origin"), [])
        with self.assertRaises(GitError): self.repo.outgoing("invalid", "origin")

    def test_renamed_guard_still_checked_conservatively(self):
        self.write("src/parser.py", "if not value:\n    raise ValueError('empty')\n")
        sha = self.commit()
        store = Store(self.repo)
        self.addCleanup(store.close)
        seed(store, sha)
        self.git("mv", "src/parser.py", "src/new.py")
        self.assertEqual(check(self.repo, store, self.repo.changes())["verdict"], "RED")

    def test_pagination_and_rate_limit(self):
        store = Store(self.repo)
        self.addCleanup(store.close)
        client = GitHub(store)
        with patch.object(client, "get", side_effect=[[{}]*100, [{"last": True}]]) as get:
            self.assertEqual(len(list(client.pages("/items"))), 101)
            self.assertIn("page=2", get.call_args.args[0])
        error = urllib.error.HTTPError("https://api.github.com", 429, "limited", {}, None)
        with patch("urllib.request.urlopen", side_effect=error):
            with self.assertRaisesRegex(APIError, "rate/access limit"): client.get("/items")

    def test_etag_304_uses_cached_body(self):
        store = Store(self.repo)
        self.addCleanup(store.close)
        store.db.execute("INSERT INTO api_cache VALUES (?,?,?)", ("/items", '"etag"', '[{"id": 1}]'))
        error = urllib.error.HTTPError("https://api.github.com", 304, "not modified", {}, None)
        with patch("urllib.request.urlopen", side_effect=error) as request:
            self.assertEqual(GitHub(store).get("/items"), [{"id": 1}])
            self.assertEqual(request.call_args.args[0].get_header("If-none-match"), '"etag"')

    def test_staged_but_not_unstaged_secret(self):
        self.write("a.py", "pass\n")
        self.commit()
        (self.path / "a.py").write_text('password="synthetic-password"\n')
        self.assertEqual(self.repo.changes(), [])
