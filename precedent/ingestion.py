"""Bounded GitHub REST ingestion. Synthetic fixtures never enter this path."""
import json
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone


class APIError(RuntimeError):
    pass


class GitHub:
    def __init__(self, store):
        self.store = store

    def get(self, path):
        headers = {"Accept": "application/vnd.github+json", "User-Agent": "Precedent-Bouncer",
                   "X-GitHub-Api-Version": "2022-11-28"}
        token = os.environ.get("GITHUB_TOKEN")
        if token:
            headers["Authorization"] = "Bearer " + token
        cached = self.store.db.execute("SELECT * FROM api_cache WHERE path=?", (path,)).fetchone()
        if cached and cached["etag"]:
            headers["If-None-Match"] = cached["etag"]
        try:
            request = urllib.request.Request("https://api.github.com" + path, headers=headers)
            with urllib.request.urlopen(request, timeout=20) as response:
                data = json.load(response)
                self.store.db.execute("INSERT OR REPLACE INTO api_cache VALUES (?,?,?)",
                                      (path, response.headers.get("ETag", ""), json.dumps(data)))
                self.store.db.commit()
                return data
        except urllib.error.HTTPError as exc:
            if exc.code == 304 and cached:
                return json.loads(cached["payload"])
            if exc.code in (403, 429):
                raise APIError("GitHub rate/access limit. Retry later or set GITHUB_TOKEN; cached checks still work.") from None
            raise APIError(f"GitHub HTTP {exc.code}; ingestion incomplete.") from None
        except (OSError, ValueError) as exc:
            raise APIError("GitHub unavailable or response invalid; ingestion incomplete.") from None

    def pages(self, path):
        for page in range(1, 101):
            sep = "&" if "?" in path else "?"
            data = self.get(f"{path}{sep}per_page=100&page={page}")
            if not isinstance(data, list):
                raise APIError("Unexpected GitHub collection response.")
            yield from data
            if len(data) < 100:
                return
        raise APIError("Pagination safety limit reached; coverage remains incomplete.")


def ingest(repo, store, owner_repo, limit=40, refresh=False, progress=print, client=None):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", owner_repo):
        raise ValueError("Use OWNER/REPOSITORY.")
    previous = store.get("repository")
    if previous and previous.lower() != owner_repo.lower():
        raise ValueError("This evidence store is bound to another repository.")
    remote = repo.run("remote", "get-url", "origin", check=False).strip()
    match = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", remote)
    if match and match.group(1).lower() != owner_repo.lower():
        raise ValueError("Requested repository differs from origin.")
    if store.get("synthetic") == "1":
        raise ValueError("Synthetic demo database cannot be mixed with real ingestion.")
    store.set("repository", owner_repo)
    store.set("ingestion_status", "incomplete")
    client = client or GitHub(store)
    prefix = "/repos/" + owner_repo
    shas = repo.run("log", f"-{limit}", "--format=%H").splitlines()
    # Add blamed commits relevant to the staged deletion even outside the window.
    for change in repo.changes():
        for line, _ in change.removed:
            shas.append(repo.blame(change.old_path, line, change.base)["sha"])
    done_prs = set()
    for sha in dict.fromkeys(shas):
        if store.covered(sha) and not refresh:
            continue
        progress("Ingesting commit " + sha[:12])
        commit = client.get(prefix + "/commits/" + sha)
        store.db.execute("INSERT OR REPLACE INTO commits VALUES (?,?)", (sha, commit["commit"]["message"]))
        prs = list(client.pages(prefix + "/commits/" + sha + "/pulls"))
        for pr in prs:
            number = pr["number"]
            store.db.execute("INSERT OR IGNORE INTO commit_pr VALUES (?,?)", (sha, number))
            if number in done_prs:
                continue
            full = client.get(prefix + f"/pulls/{number}")
            store.document("pr", full)
            files = list(client.pages(prefix + f"/pulls/{number}/files"))
            reviews = list(client.pages(prefix + f"/pulls/{number}/comments"))
            store.db.execute("DELETE FROM files WHERE pr=?", (number,))
            store.db.execute("DELETE FROM reviews WHERE pr=?", (number,))
            store.db.execute("DELETE FROM pr_issue WHERE pr=?", (number,))
            for item in files:
                store.db.execute("INSERT OR IGNORE INTO files VALUES (?,?)", (number, item["filename"]))
            for item in reviews:
                store.db.execute("INSERT OR REPLACE INTO reviews VALUES (?,?,?,?,?,?)", (
                    item["id"], number, item["path"], item.get("body", ""), item.get("html_url", ""), item.get("created_at", "")))
            # Explicit local closing references only; not every arbitrary #number.
            body = (full.get("body") or "")
            refs = re.findall(r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+#(\d+)\b", body)
            refs += re.findall(r"(?i)\b(?:fix(?:es|ed)?|close[sd]?|resolve[sd]?)\s+https://github\.com/" + re.escape(owner_repo) + r"/issues/(\d+)\b", body)
            for issue_id in set(map(int, refs)):
                issue = client.get(prefix + f"/issues/{issue_id}")
                if "pull_request" not in issue:
                    store.document("issue", issue)
                    store.db.execute("INSERT OR IGNORE INTO pr_issue VALUES (?,?)", (number, issue_id))
            done_prs.add(number)
        store.mark(sha)
        store.db.commit()
    store.set("ingestion_status", "complete_bounded_sample")
    store.set("last_ingested", datetime.now(timezone.utc).isoformat())
    return len(set(shas))
