"""Repository-local evidence store, cached API responses, explicit coverage."""
import json
import sqlite3
from datetime import datetime, timezone


class Store:
    def __init__(self, repo):
        self.path = repo.gitdir / "precedent.sqlite3"
        self.db = sqlite3.connect(self.path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS commits(sha TEXT PRIMARY KEY, summary TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS documents(
          kind TEXT NOT NULL, id INTEGER NOT NULL, body TEXT NOT NULL,
          url TEXT NOT NULL, stamp TEXT NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS commit_pr(sha TEXT, pr INTEGER, PRIMARY KEY(sha,pr));
        CREATE TABLE IF NOT EXISTS pr_issue(pr INTEGER, issue INTEGER, PRIMARY KEY(pr,issue));
        CREATE TABLE IF NOT EXISTS files(pr INTEGER, path TEXT, PRIMARY KEY(pr,path));
        CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, pr INTEGER,
          path TEXT, body TEXT, url TEXT, stamp TEXT);
        CREATE TABLE IF NOT EXISTS coverage(sha TEXT PRIMARY KEY, checked TEXT);
        CREATE TABLE IF NOT EXISTS api_cache(path TEXT PRIMARY KEY, etag TEXT, payload TEXT);
        CREATE TABLE IF NOT EXISTS ai_cache(hash TEXT PRIMARY KEY, payload TEXT, created REAL);
        CREATE INDEX IF NOT EXISTS review_pr ON reviews(pr);
        CREATE INDEX IF NOT EXISTS file_path ON files(path);
        """)

    def set(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, str(value)))
        self.db.commit()

    def get(self, key, default=None):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else default

    def document(self, kind, item):
        self.db.execute("INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?)",
                        (kind, item["number"], (item.get("title") or "") + "\n" + (item.get("body") or ""),
                         item.get("html_url", ""), item.get("created_at", "")))

    def evidence(self, sha):
        result = []
        for row in self.db.execute("SELECT pr FROM commit_pr WHERE sha=?", (sha,)):
            pr = row[0]
            result.extend(dict(r) for r in self.db.execute("SELECT * FROM documents WHERE kind='pr' AND id=?", (pr,)))
            result.extend(dict(r) for r in self.db.execute("SELECT d.* FROM documents d JOIN pr_issue p ON d.id=p.issue WHERE d.kind='issue' AND p.pr=?", (pr,)))
            result.extend({"kind": "review", "id": r["id"], "body": r["body"], "url": r["url"], "stamp": r["stamp"], "path": r["path"]}
                          for r in self.db.execute("SELECT * FROM reviews WHERE pr=?", (pr,)))
        return sorted({(r["kind"], r["id"]): r for r in result}.values(), key=lambda r: r["stamp"])

    def covered(self, sha):
        return self.db.execute("SELECT 1 FROM coverage WHERE sha=?", (sha,)).fetchone() is not None

    def mark(self, sha):
        self.db.execute("INSERT OR REPLACE INTO coverage VALUES (?,?)", (sha, datetime.now(timezone.utc).isoformat()))

    def close(self):
        self.db.commit()
        self.db.close()
