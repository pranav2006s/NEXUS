import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from .gitops import Repo, GitError
from .storage import Store
from .analysis import check, redact
from .ingestion import ingest, APIError
from .ai import commit_message, explain
from .hooks import install, original, prepare


def safe(text):
    return re.sub(r"[\x00-\x08\x0b-\x1f\x7f]", "", redact(str(text)))


def emit(data, as_json=False):
    # Scrub all output, including cached historical prose and terminal escapes.
    def scrub(value):
        if isinstance(value, str): return safe(value)
        if isinstance(value, dict): return {k: scrub(v) for k, v in value.items()}
        if isinstance(value, list): return [scrub(v) for v in value]
        return value
    clean = scrub(data)
    if as_json:
        print(json.dumps(clean, indent=2)); return
    try:
        from rich.console import Console
        console = Console()
        def out(text, style=None): console.print(text, style=style, markup=False, highlight=False)
    except ImportError:
        def out(text, style=None): print(text)
    if clean.get("synthetic"):
        out("SYNTHETIC DEMO DATA — not real GitHub evidence", "bold yellow")
    if "verdict" in clean:
        level = clean["verdict"]
        out(f"{level} | RED {clean['counts']['RED']} · YELLOW {clean['counts']['YELLOW']} · GREEN findings {clean['counts']['GREEN']}", {"RED": "bold red", "YELLOW": "bold yellow", "GREEN": "bold green"}[level])
        out("Scope: " + clean["scope"])
        out("Affected files: " + (", ".join(clean["files"]) or "none"))
        for item in clean["findings"]:
            out(f"\n[{item['level']}] {item['kind']} {item['path']}:{item['line']}")
            out(item["message"])
            if item.get("commit"): out("Blamed commit: " + item["commit"])
            for e in item["evidence"]:
                out(f"  {e['kind']} #{e['id']}: {e['body'][:500]}")
                if e["url"]: out("  " + e["url"])
        out(clean["note"])
    else:
        out(json.dumps(clean, indent=2, ensure_ascii=False))


def parser():
    p = argparse.ArgumentParser(prog="precedent", description="Evidence-backed local Git checks")
    sub = p.add_subparsers(dest="command", required=True)
    i = sub.add_parser("ingest", help="Fetch bounded GitHub evidence (network required)")
    i.add_argument("repository"); i.add_argument("--limit", type=int, default=40)
    i.add_argument("--refresh", action="store_true")
    c = sub.add_parser("check", help="Check staged changes; exit 1 RED, 0 YELLOW/GREEN, 2 error")
    c.add_argument("--json", action="store_true")
    w = sub.add_parser("why", help="Explain a committed line at HEAD or --ref")
    w.add_argument("location"); w.add_argument("--ref", default="HEAD"); w.add_argument("--json", action="store_true")
    sub.add_parser("commit-message", help="Suggest a message for staged changes")
    h = sub.add_parser("install-hooks"); h.add_argument("--chain-existing", action="store_true")
    sub.add_parser("status")
    h = sub.add_parser("_hook", help=argparse.SUPPRESS)
    h.add_argument("kind", choices=["pre-push", "prepare-commit-msg"])
    h.add_argument("backup"); h.add_argument("args", nargs="*")
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    store = None
    try:
        repo = Repo()
        store = Store(repo)
        if args.command == "status":
            emit(dict(repository=str(repo.root), head=repo.head(), database=str(store.path),
                      github_repository=store.get("repository"), ingestion=store.get("ingestion_status", "not started"),
                      covered_commits=store.db.execute("SELECT count(*) FROM coverage").fetchone()[0],
                      last_ingested=store.get("last_ingested"), synthetic=store.get("synthetic") == "1",
                      ai_enabled=os.environ.get("PRECEDENT_AI") == "1", model=os.environ.get("PRECEDENT_MODEL", "gemma3:4b")))
        elif args.command == "ingest":
            if not 1 <= args.limit <= 1000: raise ValueError("--limit must be between 1 and 1000.")
            n = ingest(repo, store, args.repository, args.limit, args.refresh)
            print(f"Cached evidence for {n} selected commits. Scope is bounded, not the entire repository history.")
        elif args.command == "check":
            report = check(repo, store, repo.changes())
            emit(report, args.json)
            return int(report["verdict"] == "RED")
        elif args.command == "why":
            path, sep, line = args.location.rpartition(":")
            if not sep or not path or not line.isdigit(): raise ValueError("Use FILE:LINE with a positive line number.")
            ref = repo.run("rev-parse", "--verify", "--end-of-options", args.ref + "^{commit}").strip()
            info = repo.blame(path, int(line), ref)
            evidence = store.evidence(info["sha"])
            explanation, mode = explain(evidence)
            emit(dict(**info, synthetic=store.get("synthetic") == "1", evidence=evidence,
                      explanation=explanation or "GitHub historical evidence unavailable. Run ingest.", mode=mode,
                      note="Blame identifies the last modifying commit, not necessarily original intent. Events sorted by source timestamp."), args.json)
        elif args.command == "commit-message":
            message, mode = commit_message(repo, store)
            print(safe(message or "No staged changes."))
            print("Mode: " + mode, file=sys.stderr)
        elif args.command == "install-hooks":
            print("Hooks installed at " + str(install(repo, args.chain_existing)))
        elif args.command == "_hook":
            data = sys.stdin.read() if args.kind == "pre-push" else None
            result = original(args.backup, args.args, data)
            if result: return result
            if args.kind == "prepare-commit-msg": return prepare(repo, store, args.args)
            if os.environ.get("PRECEDENT_SKIP") == "1":
                print("Precedent check explicitly bypassed (PRECEDENT_SKIP=1).", file=sys.stderr)
                return 0
            changes = repo.outgoing(data, args.args[0] if args.args else "origin") + repo.changes()
            report = check(repo, store, changes)
            report["scope"] = "outgoing commit patches (all parents) plus staged changes"
            emit(report)
            return int(report["verdict"] == "RED")
        return 0
    except (GitError, APIError, ValueError, OSError, sqlite3.Error, subprocess.TimeoutExpired) as exc:
        # Unknown OS/DB errors may contain paths or sensitive fragments.
        detail = str(exc) if isinstance(exc, (GitError, APIError, ValueError)) else type(exc).__name__
        print("ERROR: " + safe(detail) + ". Analysis incomplete; no GREEN verdict.", file=sys.stderr)
        return 2
    finally:
        if store: store.close()
