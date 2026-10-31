"""Preserve existing hooks only on explicit --chain-existing installation."""
from pathlib import Path
import os
import shlex
import subprocess
import sys

MARKER = "# Precedent Bouncer managed hook v1"


def hook_dir(repo):
    configured = repo.run("config", "--get", "core.hooksPath", check=False).strip()
    path = Path(configured) if configured else repo.gitdir / "hooks"
    return path if path.is_absolute() else repo.root / path


def install(repo, chain=False):
    directory = hook_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    names = ("pre-push", "prepare-commit-msg")
    # Preflight both hooks before altering either.
    for name in names:
        path = directory / name
        if path.is_symlink():
            raise ValueError("Refusing to replace a symlink hook.")
        if path.exists() and MARKER not in path.read_text(errors="replace"):
            if not chain:
                raise ValueError("Existing hooks found. Review them, then use install-hooks --chain-existing to preserve and chain them.")
            if path.with_name(name + ".precedent-original").exists():
                raise ValueError("Hook backup already exists; resolve it before installing.")
    for name in names:
        path = directory / name
        backup = path.with_name(name + ".precedent-original")
        if path.exists() and MARKER not in path.read_text(errors="replace"):
            path.rename(backup)
        bootstrap = "import sys; sys.path.insert(0, " + repr(str(Path(__file__).resolve().parent.parent)) + "); from precedent.cli import main; sys.exit(main())"
        command = [sys.executable, "-c", bootstrap, "_hook", name, str(backup)]
        path.write_text("#!/bin/sh\n" + MARKER + "\nexec " + shlex.join(command) + ' "$@"\n')
        path.chmod(0o755)
    return directory


def original(path, args, stdin=None):
    path = Path(path)
    if path.exists() and os.access(path, os.X_OK):
        return subprocess.run([str(path), *args], input=stdin, text=True).returncode
    return 0


def prepare(repo, store, args):
    from .ai import commit_message
    if not args:
        raise ValueError("Missing commit message path.")
    # Sources message/template/merge/squash/commit are intentionally untouched.
    if len(args) > 1 and args[1]:
        return 0
    path = Path(args[0])
    text = path.read_text()
    comment = repo.run("config", "--get", "core.commentChar", check=False).strip() or "#"
    if comment == "auto":
        return 0
    if any(line.strip() and not line.lstrip().startswith(comment) for line in text.splitlines()):
        return 0
    message, mode = commit_message(repo, store)
    print("Precedent commit suggestion: " + mode, file=sys.stderr)
    if message:
        path.write_text(message + "\n\n" + text)
    return 0
