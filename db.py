from contextlib import contextmanager
import hashlib
import time
import psycopg
from psycopg.rows import dict_row
from fastapi import HTTPException


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


class Database:
    def __init__(self, url):
        self.url = url

    @contextmanager
    def connect(self):
        with psycopg.connect(self.url, row_factory=dict_row, connect_timeout=10) as db:
            yield db

    def limit(self, key, maximum, seconds=3600):
        with self.connect() as db:
            row = db.execute('''INSERT INTO nexus_limits VALUES (%s,%s,1)
                ON CONFLICT(key) DO UPDATE SET
                  count=CASE WHEN nexus_limits.bucket=EXCLUDED.bucket THEN nexus_limits.count+1 ELSE 1 END,
                  bucket=EXCLUDED.bucket RETURNING count''', (key, int(time.time()) // seconds)).fetchone()
        if row['count'] > maximum:
            raise HTTPException(429, 'Request limit reached; retry later', headers={'Retry-After': str(seconds)})
