import subprocess
import tempfile
import unittest
from pathlib import Path
from precedent.gitops import Repo
from precedent.storage import Store


class RepoCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.repo = Repo(self.path)

    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.path, check=True, capture_output=True, text=True).stdout.strip()

    def write(self, name, text):
        target = self.path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        self.git("add", "--", name)

    def commit(self, message="fix(parser): guard empty input"):
        self.git("commit", "-qm", message)
        return self.repo.head()


class CoreTests(RepoCase):
    def test_diff_blame_store(self):
        self.write("src/a b.py", "if not value:\n    raise ValueError('empty')\n")
        sha = self.commit()
        self.write("src/a b.py", "pass\n")
        change = self.repo.changes()[0]
        self.assertEqual(change.removed[0][0], 1)
        self.assertEqual(self.repo.blame(change.path, 1)["sha"], sha)
        store = Store(self.repo)
        store.set("repository", "test/demo")
        store.close()
        store = Store(self.repo)
        self.assertEqual(store.get("repository"), "test/demo")
        store.close()

    def test_unborn(self):
        self.write("new.py", "print('hello')\n")
        self.assertEqual(self.repo.changes()[0].added, [(1, "print('hello')")])
