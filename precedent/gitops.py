"""All Git commands use argument arrays; no shell evaluation or external diff."""
from dataclasses import dataclass
from pathlib import Path
import re
import subprocess


class GitError(RuntimeError):
    pass


@dataclass
class Change:
    path: str
    old_path: str
    base: str
    removed: list[tuple[int, str]]
    added: list[tuple[int, str]]
    binary: bool = False


class Repo:
    def __init__(self, path="."):
        self.root = Path(path).resolve()
        self.root = Path(self.run("rev-parse", "--show-toplevel").strip())
        self.gitdir = Path(self.run("rev-parse", "--absolute-git-dir").strip())

    def run(self, *args, input=None, check=True):
        p = subprocess.run(["git", "-c", "core.quotePath=false", *args], cwd=self.root,
                           input=input, text=True, encoding="utf-8", errors="replace",
                           capture_output=True, timeout=60)
        if p.returncode and check:
            # Do not reflect Git stderr: remote URLs can contain credentials.
            raise GitError(f"Git {args[0]} failed (exit {p.returncode}); check repository/ref/path.")
        return p.stdout

    def head(self):
        return self.run("rev-parse", "--verify", "HEAD", check=False).strip()

    def empty_tree(self):
        return self.run("hash-object", "-t", "tree", "--stdin", input="").strip()

    def changes(self, base=None, tip=None):
        base = base or self.head() or self.empty_tree()
        target = [base, tip] if tip else ["--cached", base]
        names = self.run("diff", "--no-ext-diff", "--no-renames", "--name-only", "-z", *target, "--")
        result = []
        for path in filter(None, names.split("\0")):
            patch = self.run("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--unified=0", *target, "--", path)
            removed, added = [], []
            old = new = None
            for line in patch.splitlines():
                m = re.match(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@", line)
                if m:
                    old, new = map(int, m.groups())
                elif old is not None:
                    if line.startswith("-"):
                        removed.append((old, line[1:])); old += 1
                    elif line.startswith("+"):
                        added.append((new, line[1:])); new += 1
                    elif line.startswith(" "):
                        old += 1; new += 1
            result.append(Change(path, path, base, removed, added,
                                 "Binary files " in patch or "Subproject commit " in patch))
        return result

    def blame(self, path, line, ref=None):
        if line < 1:
            raise GitError("Line numbers start at 1.")
        raw = self.run("blame", "--line-porcelain", "-L", f"{line},{line}", ref or "HEAD", "--", path)
        sha = raw.splitlines()[0].split()[0]
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise GitError("Cannot identify a committed line.")
        return {"sha": sha, "summary": next((s[8:] for s in raw.splitlines() if s.startswith("summary ")), ""),
                "line": line, "path": path}

    def outgoing(self, updates, remote):
        """Each outgoing commit is checked, including secrets later deleted."""
        commits = set()
        for update in updates.splitlines():
            fields = update.split()
            if len(fields) != 4:
                raise GitError("Malformed pre-push ref update.")
            _, local, _, old = fields
            if not re.fullmatch(r"[0-9a-f]{40,64}", local) or not re.fullmatch(r"[0-9a-f]{40,64}", old):
                raise GitError("Invalid push object ID.")
            if set(local) == {"0"}:
                continue
            tip = self.run("rev-parse", "--verify", local + "^{commit}").strip()
            args = ["rev-list", tip]
            if set(old) != {"0"}:
                self.run("cat-file", "-e", old + "^{commit}")
                args += ["^" + old]
            else:
                # Conservative: all reachable history, avoids trusting stale remote refs.
                pass
            commits.update(self.run(*args, "--").splitlines())
        changes = []
        for sha in sorted(commits):
            parents = self.run("rev-list", "--parents", "-n", "1", sha).split()[1:]
            for parent in parents or [self.empty_tree()]:
                changes.extend(self.changes(parent, sha))
        return changes
