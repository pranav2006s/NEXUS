# Validation record

## Version 0.3 default-on free-tier API adapter

- `python -m pytest -q`: **45 passed**. Core regressions remain; the obsolete
  Ollama selector test was replaced by a missing-key test and Gemini tests added.
- `python -m compileall -q precedent scripts`: passed.
- Live local Uvicorn HTTP smoke test: version 0.3, default-enabled configuration,
  missing-key diagnostics on why/check, secret-blocked cloud analysis and preserved
  deterministic RED verdict all passed with no Gemini credentials.
- Mocked Gemini tests: generation request shape, exact endpoint and header,
  generated subject from actual diff, grounded citations, source-bound cache,
  429 without retries/provider switching, timeout, malformed output, invented
  citations, truncation/finish failure, payload limits, explicit disable,
  redaction and added/removed secret blocking.
- Web tests verify generated-result metadata and unavailable/blocked states.
- Default provider/model: Gemini / gemini-3.5-flash-lite. Google's published
  pricing lists a free tier; account eligibility/quota and billing remain an
  operator responsibility. Billing cannot be established from an API key.
- Live Google inference has NOT been executed: no user key was supplied. Provider
  tests use synthetic responses. No quota, latency or account access is claimed.
- No paid fallback, search tool or auto-retry is configured. Free API access is
  not unlimited. Instructions explicitly require a Free-tier project without
  paid billing; a paid key on the same endpoint can incur charges.
- The local Ollama selector is retired. Tests have a default offline fixture;
  targeted provider tests explicitly enable mocked AI. No external inference is
  performed by the test suite.
- The existing Starlette/HTTPX test-client deprecation warning remains nonfatal.
- AI-generated prose is not guaranteed factually correct; only structure and
  supplied citation identity are validated. Deterministic findings remain
  authoritative for the push gate. See AI_SETUP.md for privacy/coverage limits.

The records below describe earlier builds and their historical validation.

## Version 0.2 web adapter verification

- `python -m pytest -q`: **32 passed** (21 original tests, 11 web tests).
- `python -m compileall -q precedent scripts`: passed.
- `node --check examples/api-client.mjs`: passed syntax check.
- Started an actual Uvicorn process on loopback and issued HTTP requests:
  health, authenticated registration, combined check (2 RED / 1 YELLOW),
  evidence-backed why, commit-message response and OpenAPI version all passed.
- Web tests cover bearer authentication, origins/CORS, Host validation, 1 MiB
  request limits, safe validation errors, root/path restrictions, registration,
  persistence, staging, hook preservation, commit-range secret detection,
  background ingestion success/failure, busy-repository rejection, restart
  interruption state and OpenAPI authentication metadata.
- Original CLI/core/Git hook tests remain passing without changes to their logic.
- Web ingestion tests use controlled function responses. The original live
  GitHub validation below covers the shared ingestion implementation; a new live
  GitHub request through the web job endpoint was not needed or claimed.
- FastAPI 0.162.0, Uvicorn 0.54.0 and HTTPX 0.28.1 were installed for this run.
  Starlette emits a test-client deprecation warning for HTTPX; tests still pass.
- Actual browser frontend rendering, Windows/macOS execution, public deployment,
  multi-user isolation and actual Gemma inference are not verified here.
- Single-process locking: use one server worker and avoid concurrent external
  modifications to the same Git index. See `WEB_BACKEND.md` for deployment limits.

The record below describes the original CLI build.

Build session: 31 October 2026 (Asia/Kolkata). Linux, Python 3.12.14, Git 2.51.1.

## Executed successfully

- `python -m pip install -e '.[terminal,dev]'`: installed editable package and CLI.
- `python -m compileall -q precedent scripts`: no compilation errors.
- `python -m pytest -q`: **21 passed** after removing duplicate inherited tests.
- Real Git staged diff, blame and persistent SQLite round trip.
- Unborn repository; binary-change incomplete warning; unstaged changes excluded.
- Guard deletion RED; replacement guard YELLOW; missing history YELLOW.
- Secret patterns and output redaction; review forecast and combined findings.
- Mock GitHub ingestion with PR/issue/review associations and incremental skipping.
- Pagination, ETag 304 reuse, rate-limit failure, offline failure/incomplete state.
- Real local bare-remote push rejected for a committed secret subsequently removed.
- Explicit bypass allows that synthetic test push.
- Existing hook receives stdin and its exit code survives the bypass.
- Existing hooks refused without explicit chaining; manual commit messages preserved.
- Actual source-less Git commit gets a generated message; `-m` remains unchanged.
- New remote branch history scanned; deletion updates and malformed input handled.
- Missing local model and invalid model indices use fallback; valid index accepted.
- Synthetic demo: `why`, combined RED report (2 RED, 1 YELLOW), proposed message,
  installed hooks, blocked push, corrected changes, GREEN, commit, successful push.
  Rehearsal found `git rm config.py` required `-f` for the staged synthetic file;
  the corrected command was executed successfully and documented.

## Live GitHub validation

A separate read-only clone of `https://github.com/octocat/Hello-World.git` was used.
`precedent ingest octocat/Hello-World --limit 10` completed for all three local
commits. `precedent why README:1 --json` traced the line to commit
`762941318ee16e59dabbacb1b4049eec22f0d303`, associated it with
`https://github.com/octocat/Hello-World/pull/6`, and displayed retrieved review
comments with their real source URLs. Status reported `complete_bounded_sample`
and three covered commits. This validates live PR/review retrieval; an associated
issue was not available in that sample, so issue-link behavior is covered by the
controlled API test rather than claimed as live-validated.

The third-party clone and its data are excluded from the deliverable.

## Not verified / remaining limitations

- Ollama is not installed here. Actual Gemma inference, performance, download,
  hardware suitability and prize eligibility were not tested.
- Tests ran on Linux. Windows Git Bash / PowerShell and macOS were not exercised.
- Large repositories, Git LFS, malicious Git configurations, and massive branch
  histories were not stress-tested. No production security guarantee is claimed.
- Review categories are keyword matches across cached inline comments; author
  roles are not validated. Do not describe these as verified maintainer demands.
- Free-form AI explanations are intentionally excluded; the model selects only
  grounded candidates. Fence findings group by file and blamed commit.
- A public project repository has not been created or pushed. No remote target
  or account for publication was supplied.
- No backup presentation video was produced. The demonstration script is provided.

## Preserve development history

The archive includes `project-history.bundle`, containing the local implementation
commits. To restore a normal Git checkout after extracting the archive:

```bash
git clone project-history.bundle precedent-bouncer-restored
```

The ordinary source files are also included for direct use. Runtime SQLite files,
fake demo working trees, caches, installed dependencies and external repositories
are not included. Recreate the demo with `scripts/create_demo.py`.
