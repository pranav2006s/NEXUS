"""Transparent heuristics; neither a semantic proof nor a security audit."""
from collections import Counter
from pathlib import PurePosixPath
import math
import re
from .gitops import GitError

PATTERNS = [
    ("AWS access key", r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    ("GitHub token", r"\b(?:gh[pousr]_[A-Za-z0-9]{36,255}|github_pat_[A-Za-z0-9_]{22,255})\b"),
    ("Private key", r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ("Credential assignment", r'''(?i)\b(?:password|passwd|api[_-]?key|access[_-]?token|client[_-]?secret)\s*[:=]\s*["'][^"'\s]{8,}["']'''),
]
GUARD = re.compile(r"\b(?:if|assert|raise|throw|validate|sanitize|check_|guard|escape|verify|limit|timeout)\b", re.I)
RISK = re.compile(r"\b(?:prevent|crash|security|vulnerab\w*|invariant|regression|overflow|validation|safeguard|empty input)\b", re.I)
CATEGORIES = {
    "tests": r"\b(?:tests?|coverage)\b",
    "error handling": r"\b(?:exception|error handling|catch|raise)\b",
    "documentation": r"\b(?:docs?|documentation|readme)\b",
    "naming and readability": r"\b(?:rename|naming|readability|readable)\b",
    "performance": r"\b(?:performance|slow|complexity|optimi[sz]e)\b",
    "security": r"\b(?:security|sanitize|vulnerability|injection)\b",
}


def finding(level, kind, path, line, message, evidence=None, **extra):
    return dict(level=level, kind=kind, path=path, line=line, message=message,
                evidence=evidence or [], **extra)


def entropy(value):
    return -sum((n / len(value)) * math.log2(n / len(value)) for n in Counter(value).values()) if value else 0


def secrets(changes):
    results = []
    for change in changes:
        for line, text in change.added:
            kinds = [name for name, pattern in PATTERNS if re.search(pattern, text)]
            if not kinds:
                tokens = re.findall(r'''["']([A-Za-z0-9+/=_-]{24,})["']''', text)
                if any(entropy(t) >= 4.3 for t in tokens):
                    results.append(finding("YELLOW", "secret", change.path, line,
                        "High-entropy string; possible credential. Inspect locally (possible false positive)."))
            elif kinds:
                results.append(finding("RED", "secret", change.path, line,
                    ", ".join(kinds) + "; remove or rotate if genuine. Potential false positive; value withheld."))
    return results


def redact(text):
    for _, pattern in PATTERNS:
        text = re.sub(pattern, "[REDACTED]", text)
    return re.sub(r'''["']([A-Za-z0-9+/=_-]{24,})["']''', '"[REDACTED STRING]"', text)


def fences(repo, store, changes):
    results = []
    for change in changes:
        if change.binary:
            results.append(finding("YELLOW", "coverage", change.path, 0, "Binary/submodule change is not inspected; analysis incomplete."))
        groups = {}
        for line, text in change.removed:
            if not text.strip():
                continue
            try:
                info = repo.blame(change.old_path, line, change.base)
                groups.setdefault(info["sha"], []).append((line, text))
            except GitError:
                results.append(finding("YELLOW", "coverage", change.path, line, "Blame unavailable; analysis incomplete."))
        for sha, lines in groups.items():
            evidence = store.evidence(sha)
            relevant = [e for e in evidence if RISK.search(e["body"]) and (e["kind"] != "review" or e.get("path") == change.old_path)]
            removed_guard = any(GUARD.search(text) for _, text in lines)
            # Replacement guard remains uncertain; never infer semantic equivalence.
            replacement_guard = any(GUARD.search(text) for _, text in change.added)
            if removed_guard and relevant:
                level = "YELLOW" if replacement_guard else "RED"
                results.append(finding(level, "fence", change.path, lines[0][0],
                    "Safeguard-like code changed; its blamed commit has risk-related evidence. " +
                    ("Replacement logic needs review." if replacement_guard else "Possible safeguard removal; verify before pushing."),
                    relevant, commit=sha))
            elif removed_guard:
                results.append(finding("YELLOW", "fence", change.path, lines[0][0],
                    "Safeguard-like code changed; historical justification is unavailable or inconclusive.", evidence, commit=sha))
            elif not store.covered(sha):
                results.append(finding("YELLOW", "coverage", change.path, lines[0][0],
                    "Historical data for blamed commit is unavailable. Run ingest; analysis incomplete.", commit=sha))
    return results


def is_test(path):
    p = PurePosixPath(path)
    return any(s in ("test", "tests", "__tests__") for s in p.parts) or p.name.startswith("test_") or bool(re.search(r"(?:_test\.|\.(?:spec|test)\.)", p.name))


def forecast(store, changes):
    results = []
    dirs = {str(PurePosixPath(c.path).parent) for c in changes if not is_test(c.path)}
    any_tests = any(is_test(c.path) for c in changes)
    for directory in sorted(dirs):
        prs = {r["pr"] for r in store.db.execute("SELECT * FROM files") if str(PurePosixPath(r["path"]).parent) == directory}
        counts = {name: set() for name in CATEGORIES}
        evidence = []
        for r in store.db.execute("SELECT * FROM reviews"):
            if r["pr"] not in prs or str(PurePosixPath(r["path"]).parent) != directory:
                continue
            for name, pattern in CATEGORIES.items():
                if re.search(pattern, r["body"], re.I):
                    counts[name].add(r["pr"])
                    if name == "tests":
                        evidence.append(dict(kind="review", id=r["id"], body=r["body"], url=r["url"], stamp=r["stamp"]))
        if len(prs) >= 3 and len(counts["tests"]) / len(prs) >= 0.5 and not any_tests:
            results.append(finding("YELLOW", "forecast", directory, 0,
                f"{len(counts['tests'])} of {len(prs)} cached PRs touching this directory mention tests in inline reviews; no test changes detected. Consider adding tests. This is a sampled pattern, not a requirement.",
                evidence, categories={k: len(v) for k, v in counts.items()}))
    return results


def check(repo, store, changes):
    from .ai import review_changes
    results = secrets(changes) + fences(repo, store, changes) + forecast(store, changes)
    if changes and not store.get("last_ingested"):
        results.append(finding("YELLOW", "coverage", "", 0, "No completed historical ingestion. Review forecast coverage unavailable."))
    if store.get("ingestion_status") == "incomplete":
        results.append(finding("YELLOW", "coverage", "", 0, "Last ingestion did not complete; cached evidence may be partial."))
    unique = {}
    for item in results:
        key = (item["level"], item["kind"], item["path"], item["line"], item.get("commit"), item["message"])
        unique[key] = item
    results = list(unique.values())
    ai = review_changes(store, changes, results)
    if ai["status"] in ("unavailable", "blocked"):
        results.append(finding("YELLOW", "ai_coverage", "", 0,
            "Basic checks only; AI assessment incomplete: " + ai["reason"] + "."))
    counts = {level: sum(r["level"] == level for r in results) for level in ("RED", "YELLOW", "GREEN")}
    level = "RED" if counts["RED"] else "YELLOW" if counts["YELLOW"] else "GREEN"
    return dict(verdict=level, counts=counts, files=sorted({c.path for c in changes}), findings=results,
                ai=ai, analysis_status=("ai_completed" if ai["status"] == "completed" else "no_changes" if not changes else "basic_checks_only"),
                synthetic=store.get("synthetic") == "1", scope="staged changes" ,
                note=("No significant risk detected in analyzed scope; GREEN is not proof of safety." if level == "GREEN" else
                      "Review the findings above. Heuristic results may include false positives; incomplete coverage is explicitly flagged."))
