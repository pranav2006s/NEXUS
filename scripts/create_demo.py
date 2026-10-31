"""Create a NEW isolated Git demo. Every issue/review is clearly synthetic."""
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from precedent.gitops import Repo
from precedent.storage import Store


def create(destination):
    root = Path(destination).resolve()
    if root.exists():
        raise ValueError("Destination already exists. Choose a new directory; nothing was overwritten.")
    root.mkdir(parents=True)
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, check=True, text=True, capture_output=True).stdout.strip()
    git("init", "-q")
    git("config", "user.name", "Synthetic Demo")
    git("config", "user.email", "demo@example.invalid")
    (root / "src").mkdir()
    parser = root / "src/parser.py"
    parser.write_text('def parse(value):\n    if not value:\n        raise ValueError("empty input")\n    return value[0]\n')
    (root / "README.md").write_text("SYNTHETIC DEMO. No real GitHub PRs, issues, or credentials.\n")
    git("add", ".")
    git("commit", "-qm", "fix(parser): prevent empty input crash")
    repo = Repo(root)
    sha = repo.head()
    store = Store(repo)
    store.set("synthetic", "1")
    store.set("repository", "synthetic/local-demo")
    store.set("last_ingested", "Synthetic fixture; not retrieved from GitHub")
    store.set("ingestion_status", "synthetic_fixture")
    store.db.execute("INSERT INTO commits VALUES (?,?)", (sha, "fix(parser): prevent empty input crash"))
    for number in range(1, 5):
        store.document("pr", {"number": number, "title": "[SYNTHETIC] Prevent empty input crash",
            "body": "Added validation to prevent empty input from reaching the parser. Fixes #5.",
            "created_at": "2026-01-02T10:00:00Z"})
        store.db.execute("INSERT INTO files VALUES (?,?)", (number, "src/parser.py"))
        if number <= 3:
            store.db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)", (number, number, "src/parser.py",
                "[SYNTHETIC] Please add tests for empty input.", "", "2026-01-02T12:00:00Z"))
    store.document("issue", {"number": 5, "title": "[SYNTHETIC] Empty input crashes parser", "body": "The parser crashes without the guard.", "created_at": "2026-01-01T10:00:00Z"})
    store.db.execute("INSERT INTO commit_pr VALUES (?,1)", (sha,))
    store.db.execute("INSERT INTO pr_issue VALUES (1,5)")
    store.mark(sha)
    store.close()
    parser.write_text("def parse(value):\n    return value[0]\n")
    # An intentionally fake AWS-shaped value; generated only in the demo.
    (root / "config.py").write_text('# SYNTHETIC NONFUNCTIONAL DEMO VALUE\napi_key = "' + 'AKIA' + 'A' * 16 + '"\n')
    git("add", "src/parser.py", "config.py")
    print("Created SYNTHETIC demo at", root)
    print("Run: precedent why src/parser.py:2; precedent check; precedent commit-message")
    return root


if __name__ == "__main__":
    create(sys.argv[1] if len(sys.argv) > 1 else "demo-workspace")
