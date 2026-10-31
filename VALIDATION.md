# Validation record — 0.3.1

Executed 31 October 2026 in Linux with Python 3.12. No live Gemini requests,
deployment, or remote writes were performed for this update.

## Source inspection

Inspected GitHub main at d5f3121 and the local pending repair. Main had Gemini
setup docs but old local-model source and no cloud_ai.py or test_cloud_ai.py.
The pending repair was the starting point; the delivered source contains both
files and their CLI, hook, SQLite and web integration. No frontend was added.
The legacy project-history.bundle in the repository describes an older snapshot;
do not restore it as the source for this release.

## Commands and results

- `python -m pytest -q`: **55 passed, 1 warning**. No skipped tests.
- `python -m compileall -q precedent scripts`: passed.
- `git diff --check HEAD`: passed.
- Starlette emits a nonfatal deprecation warning for its HTTPX TestClient backend.

## Covered behavior

Provider transport is mocked and unexpected urllib HTTP calls are rejected by an
autouse fixture. Test credentials are generated dummy strings, not real API keys.
Tests cover default enablement, explicit disable, missing key, 400/401/403/404/429/
500 errors, timeout, request headers/prompt/schema, malformed nested responses,
response and context limits, invalid/missing citations, incomplete generation,
cache reuse/source binding/corruption/expiry, and secret blocking in changed lines
and raw historical context before truncation. Model output cannot downgrade RED.

Web tests cover common AI fields and generated/cached/unavailable/disabled states
on all four AI routes, blocked changes/history, and no-change actions. Existing
bearer auth, exact-origin CORS, host checks, root and traversal boundaries, 1 MiB
body limit, safe validation errors, hook preservation, background jobs and commit
range tests remain. CLI forecast and commit-message JSON status are tested.
Core tests exercise real temporary Git repositories and local bare remotes.

## Not verified / remaining limitations

No live Gemini key, latency, free quota, project eligibility, or live model output
was tested. Official Google documentation was checked for endpoint, authentication,
model support, structured request and response format (see AI_SETUP.md).
No browser frontend, Windows/macOS execution, deployment, public multi-user auth,
load/stress tests, or comprehensive security audit is claimed. Secret scanning is
heuristic; output citations do not prove semantic correctness. One shared token
allows all registered repositories: use only a trusted local/team environment.
