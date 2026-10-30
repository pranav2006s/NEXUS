"""Persistent registry/jobs and in-process serialization for one server worker."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3
import threading
import uuid


def now():
    return datetime.now(timezone.utc).isoformat()


class State:
    def __init__(self, directory):
        self.path = Path(directory) / "web.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.guard = threading.Lock()
        self.locks = {}
        self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="precedent")
        with self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS repositories(id TEXT PRIMARY KEY, path TEXT UNIQUE, name TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, repo_id TEXT, status TEXT, progress TEXT,
                result TEXT, error TEXT, created TEXT, updated TEXT);
            UPDATE jobs SET status='interrupted', error='Server restarted; submit ingestion again.'
                WHERE status IN ('queued','running');
            """)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db: yield db
        finally:
            db.close()

    def lock(self, path):
        with self.guard:
            return self.locks.setdefault(str(path), threading.Lock())

    def register(self, path):
        with self.db() as db:
            db.execute("INSERT OR IGNORE INTO repositories VALUES (?,?,?)", (uuid.uuid4().hex, str(path), path.name))
            return dict(db.execute("SELECT * FROM repositories WHERE path=?", (str(path),)).fetchone())

    def repositories(self):
        with self.db() as db:
            return [dict(row) for row in db.execute("SELECT * FROM repositories ORDER BY name")]

    def repository(self, repo_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM repositories WHERE id=?", (repo_id,)).fetchone()
            return dict(row) if row else None

    def new_job(self, repo_id):
        job_id = uuid.uuid4().hex
        with self.db() as db:
            db.execute("INSERT INTO jobs VALUES (?,?,?,?,?,?,?,?)", (job_id, repo_id, "queued", "Waiting", None, None, now(), now()))
        return job_id

    def update_job(self, job_id, status, progress="", result=None, error=None):
        with self.db() as db:
            db.execute("UPDATE jobs SET status=?,progress=?,result=?,error=?,updated=? WHERE id=?",
                       (status, progress, json.dumps(result) if result is not None else None, error, now(), job_id))

    def job(self, job_id):
        with self.db() as db:
            row = db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if not row: return None
            result = dict(row)
            result["result"] = json.loads(result["result"]) if result["result"] else None
            return result
