import io
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch
from test_core import RepoCase
from precedent.storage import Store
from precedent.ai import commit_message
from precedent.cloud_ai import generate
from precedent.hooks import install, prepare


class HookTests(RepoCase):
    def test_committed_then_removed_secret_blocks_real_push(self):
        self.write("README.md", "demo\n")
        self.commit("docs: initial")
        remote = self.path / "remote.git"
        self.git("init", "--bare", "-q", str(remote))
        self.git("remote", "add", "origin", str(remote))
        self.git("push", "-q", "origin", "HEAD:refs/heads/main")
        self.write("config.py", 'api_key="' + 'AKIA' + 'B'*16 + '"\n')
        self.commit("feat: configuration")
        self.write("config.py", "# removed\n")
        self.commit("fix: remove configuration")
        install(self.repo)
        p = subprocess.run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=self.path, capture_output=True, text=True)
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("RED", p.stdout)
        self.assertNotIn('AKIA' + 'B'*16, p.stdout + p.stderr)
        env = dict(os.environ, PRECEDENT_SKIP="1")
        p = subprocess.run(["git", "push", "origin", "HEAD:refs/heads/main"], cwd=self.path, env=env, capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_existing_hooks_preserved_and_receive_stdin(self):
        self.write("a", "a\n")
        self.commit()
        directory = self.repo.gitdir / "hooks"
        hook = directory / "pre-push"
        hook.write_text("#!/bin/sh\ncat > original-input.txt\nexit 7\n")
        hook.chmod(0o755)
        with self.assertRaises(ValueError): install(self.repo)
        self.assertFalse((directory / "prepare-commit-msg").exists())
        install(self.repo, chain=True)
        content = "refs/heads/main " + self.repo.head() + " refs/heads/main " + "0"*40 + "\n"
        p = subprocess.run([str(hook), "origin", "demo"], cwd=self.path, input=content, text=True, capture_output=True,
                           env=dict(os.environ, PRECEDENT_SKIP="1"))
        self.assertEqual(p.returncode, 7)
        self.assertEqual((self.path / "original-input.txt").read_text(), content)

    def test_manual_commit_message_preserved(self):
        self.write("a.py", "pass\n")
        self.commit()
        self.write("a.py", "print('hi')\n")
        store = Store(self.repo)
        self.addCleanup(store.close)
        path = self.path / "MESSAGE"
        path.write_text("My manually written message\n")
        prepare(self.repo, store, [str(path)])
        self.assertEqual(path.read_text(), "My manually written message\n")
        path.write_text("# comment only\n")
        prepare(self.repo, store, [str(path)])
        self.assertTrue(path.read_text().startswith("fix(a): update a.py"))

    def test_prepare_hook_actual_commit(self):
        self.write("a.py", "pass\n")
        self.commit("feat(core): initial")
        install(self.repo)
        self.write("a.py", "print('hello')\n")
        env = dict(os.environ, GIT_EDITOR="true")
        subprocess.run(["git", "commit", "-q"], cwd=self.path, env=env, check=True, capture_output=True)
        self.assertEqual(self.git("log", "-1", "--format=%s"), "fix(a): update a.py")
        self.write("a.py", "print('manual')\n")
        self.commit("manual message")
        self.assertEqual(self.git("log", "-1", "--format=%s"), "manual message")

    def test_new_branch_scans_history(self):
        self.write("a", "initial\n")
        self.commit()
        self.write("a", 'password="synthetic-password"\n')
        sha = self.commit()
        updates = f"refs/heads/new {sha} refs/heads/new {'0'*40}\n"
        changes = self.repo.outgoing(updates, "origin")
        self.assertTrue(any('synthetic-password' in text for c in changes for _, text in c.added))

    def test_missing_key_is_explicit_and_offline(self):
        with patch.dict(os.environ, {"PRECEDENT_AI": "1"}), patch("urllib.request.OpenerDirector.open") as request:
            answer = generate("explain_history", "context")
            self.assertEqual(answer["reason"], "missing_api_key")
            request.assert_not_called()
