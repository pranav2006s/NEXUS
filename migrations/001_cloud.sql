-- Run once before deploying. All durable cloud data is in PostgreSQL.
BEGIN;
CREATE TABLE IF NOT EXISTS nexus_users (
  id BIGINT PRIMARY KEY, login TEXT NOT NULL, token BYTEA NOT NULL
);
CREATE TABLE IF NOT EXISTS nexus_sessions (
  hash TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES nexus_users(id) ON DELETE CASCADE,
  csrf TEXT NOT NULL, expires TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS nexus_session_user ON nexus_sessions(user_id);
CREATE TABLE IF NOT EXISTS nexus_oauth (
  hash TEXT PRIMARY KEY, verifier BYTEA NOT NULL, expires TIMESTAMPTZ NOT NULL
);
CREATE TABLE IF NOT EXISTS nexus_repositories (
  id TEXT PRIMARY KEY, user_id BIGINT NOT NULL REFERENCES nexus_users(id) ON DELETE CASCADE,
  github_id BIGINT NOT NULL, full_name TEXT NOT NULL,
  evidence BYTEA, UNIQUE(user_id, github_id)
);
CREATE TABLE IF NOT EXISTS nexus_reports (
  id TEXT PRIMARY KEY, repository_id TEXT NOT NULL REFERENCES nexus_repositories(id) ON DELETE CASCADE,
  user_id BIGINT NOT NULL REFERENCES nexus_users(id) ON DELETE CASCADE,
  action TEXT NOT NULL, result JSONB NOT NULL, created TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS nexus_report_owner ON nexus_reports(user_id, created DESC);
CREATE TABLE IF NOT EXISTS nexus_limits (
  key TEXT PRIMARY KEY, bucket BIGINT NOT NULL, count INTEGER NOT NULL
);
COMMIT;
