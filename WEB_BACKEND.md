> **Public multi-user deployment:** see [CLOUD_DEPLOYMENT.md](CLOUD_DEPLOYMENT.md) for the separate GitHub OAuth + PostgreSQL cloud API. The local companion setup below uses a different API and must not be exposed publicly.

# Website backend — version 0.3.1

The existing Python core is accessible through a FastAPI JSON API. The CLI,
SQLite evidence and both Git hooks remain available. Gemini AI is enabled by
default; configure its free-tier key using `AI_SETUP.md`.
This deliverable is the backend and a JavaScript integration client, not a
finished website frontend.

## Deployment model

**Local companion:** run the API on the developer's laptop. A local website calls
it. The API accesses that laptop's staged changes and installs hooks there.
This preserves the original local pre-push behavior.

**Hosted backend:** run the API on a server with trusted Git working copies.
Analysis, staging and hooks operate on those server copies. A hosted website
cannot install hooks in a visitor's laptop, read its Git index, or intercept its
pushes without a local companion. The backend calls Gemini; the API key never
belongs in frontend code.

This is a single-user/trusted-team backend. One bearer token grants access to all
registered repositories. Public multi-user SaaS additionally needs per-user
identity, repository authorization, isolated workers and per-user credentials.
Never embed the shared token in a publicly distributed frontend bundle.

## Windows: run the API

Open PowerShell in the extracted `precedent-bouncer` folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web,terminal,dev]"
.\.venv\Scripts\python.exe -m pytest -q
$env:GEMINI_API_KEY = "your-free-tier-project-key"
$env:PRECEDENT_REPO_ROOTS = (Get-Location).Path
$env:PRECEDENT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:8000,http://localhost:8000"
.\.venv\Scripts\python.exe -m precedent.web.server
```

`PRECEDENT_REPO_ROOTS` permits repositories inside the specified trusted folder.
Keep that terminal open. Visit `http://127.0.0.1:8000/docs` for interactive API
documentation. In a second PowerShell terminal, read the generated API token:

```powershell
Get-Content "$HOME\.precedent-web\api-token"
```

Paste just the token into the docs' **Authorize** bearer-token box. Do not share
or commit it. Newly generated token files have mode 0600 on Unix; Windows uses
the account's filesystem permissions. Alternatively supply `PRECEDENT_API_TOKEN`
with at least 32 random characters. Generate one with
`python -c "import secrets; print(secrets.token_urlsafe(32))"`.

### Test the synthetic fixture through HTTP

In the second terminal, from the project folder:

```powershell
.\.venv\Scripts\python.exe scripts\create_demo.py web-demo
$headers = @{ Authorization = "Bearer $(Get-Content "$HOME\.precedent-web\api-token" -Raw)" }
$body = @{ path = (Resolve-Path web-demo).Path } | ConvertTo-Json
$repo = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/repositories" -Headers $headers -ContentType "application/json" -Body $body
$result = Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/api/v1/repositories/$($repo.id)/check" -Headers $headers -ContentType "application/json" -Body '{}'
$result | ConvertTo-Json -Depth 20
```

Expected by default: RED, two RED findings and two YELLOW warnings (missing
tests plus AI blocked because the fake credential must not be sent to Google). The demo intentionally
contains a guard deletion and a fake credential; synthetic history is labeled.
Choose a new folder when repeating setup; the generator refuses overwrites.
Do not run real GitHub ingestion on a synthetic fixture.

## Linux / macOS

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[web,terminal,dev]'
export GEMINI_API_KEY="your-free-tier-project-key"
export PRECEDENT_REPO_ROOTS="$PWD"
precedent-server
```

Read the token in another terminal with `cat ~/.precedent-web/api-token`.
The original `precedent` CLI commands remain available.

## Endpoints

All `/api/v1` requests require `Authorization: Bearer TOKEN`. JSON requests use
`Content-Type: application/json`. Public `/health`, `/docs`, and `/openapi.json`
contain no repository results or credentials.

Let `R = /api/v1/repositories/{id}`. Registration returns a stable repository ID.

| Method / path | Request | Result |
| --- | --- | --- |
| `GET /health` | — | Service health and version |
| `GET /api/v1/repositories` | — | Registered repositories |
| `POST /api/v1/repositories` | `{"path":"absolute/repository/root"}` | Register existing trusted repo |
| `GET R/status` | — | HEAD, history coverage, AI configuration |
| `GET R/changes` | — | Staged file names and counts; no raw secret-bearing diff |
| `POST R/stage` | `{"paths":["src/parser.py"]}` | Stage named edits/additions/deletions |
| `POST R/check` | `{}` | Unified fence/secret/forecast verdict on staged changes |
| `POST R/check` | `{"scope":"commits","base":"main","tip":"HEAD"}` | Scan every outgoing commit, including later-removed secrets |
| `POST R/why` | `{"path":"src/parser.py","line":2,"ref":"HEAD"}` | Blame, evidence and grounded explanation |
| `POST R/secrets` | No body | Staged secret findings without values |
| `POST R/forecast` | No body | Staged review warnings, coverage indicator and AI status/text |
| `POST R/commit-message` | No body | Suggested message and model/fallback mode |
| `POST R/hooks` | `{"chain_existing":false}` | Install both hooks on the backend host |
| `POST R/ingest` | `{"repository":"OWNER/REPO","limit":40,"refresh":false}` | HTTP 202, job ID and polling URL |
| `GET /api/v1/jobs/{job_id}` | — | Job status, progress, result/error |

Fence Check remains part of `check`. Commit ranges are capped at 500 outgoing
commits; choose a closer base for larger histories. Omit base to scan all reachable
commits within that cap. Staged mode excludes unstaged edits: stage them first.
The stage endpoint does not edit source files. The API does not create commits
or push to GitHub. Clone real repositories onto the backend host first, register
them, then ingest. `GITHUB_TOKEN` is read only from the server environment.

## Frontend integration

This direct browser client is for a locally operated or restricted trusted-team UI.
Every person holding the shared bearer token can access all registered repositories.
Do not inject it through public frontend environment variables, ship it in a bundle,
or store it in browser persistent storage. Never put GEMINI_API_KEY in a browser.
A public frontend requires a separate authenticated server layer with per-user
repository authorization; that layer is NOT implemented here. CORS is not user
identity or authorization. Evidence and model output must be rendered as text;
validate any link's scheme and destination before making it clickable.

Copy `examples/api-client.mjs` into your frontend source. It uses standard fetch:

```javascript
import { PrecedentAPI } from "./api-client.mjs";
const api = new PrecedentAPI("http://127.0.0.1:8000", tokenFromUserInput);
const repo = await api.register(repositoryPathFromUserInput);
const report = await api.check(repo.id);
// Render report.verdict, report.counts and report.findings as text.

// For real repositories, ingest before relying on history:
const job = await api.ingest(repo.id, "OWNER/REPO");
await api.waitForJob(job.job_id, { onProgress: job => console.log(job.status) });
```

Keep the token in memory, not a public build or URL. Render historical evidence
as text, never raw HTML. RED is HTTP 200 with `push_allowed: false`: analysis
succeeded and found risks. Never display GREEN for an error/unavailable report.
Only an installed hook intercepts actual Git pushes.

Display `ai.status` from check/why/forecast/commit-message responses:
- `completed`: generated output, with `cached` indicating a reused response.
- `unavailable`: missing key/quota/network/invalid output; display `ai.reason`.
- `blocked`: suspected secrets in changes or history prevented submission.
- `disabled`: operator explicitly selected basic-only mode.
- `not_applicable`: no changes to analyze.

`analysis_status` on checks is `ai_completed`, `basic_checks_only` or `no_changes`.
`mode` on why/commit-message is `gemini-generated`, `gemini-generated-cached`, or
an explicitly labeled template mode. Basic output remains usable but is not an
AI result. AI interpretation is advisory; the gate still uses deterministic risks.
Source IDs are validated; factual correctness of generated prose is not guaranteed.

| HTTP status | Meaning |
| --- | --- |
| 200 / 201 | Result / registered repo |
| 202 | Poll the job URL |
| 400 / 422 | Correct invalid input; submitted values are not echoed |
| 401 | Missing/invalid API token |
| 403 | Origin, repository path, or hook path outside allowed boundary |
| 404 | Unknown repository or job |
| 409 | Busy repository or Git operation conflict; retry after job/correct Git state |
| 413 | Request over 1 MiB or commit range too large |
| 500 / 502 | Failed operation; no GREEN verdict |

Ingestion job states: queued, running, succeeded, failed, interrupted. Failures
remain visible as job errors. Repository operations return 409 during ingestion;
job polling and repository listing remain available. Registry/jobs persist in
`web.sqlite3`. Restart marks unfinished jobs interrupted. Resubmit ingestion to
resume from already-cached commits.

## Configuration

| Variable | Default / purpose |
| --- | --- |
| `PRECEDENT_REPO_ROOTS` | Required trusted parents; `;` separator on Windows, `:` on Unix |
| `PRECEDENT_WEB_STATE` | `~/.precedent-web`, persistent registry/jobs/token |
| `PRECEDENT_API_TOKEN` | Optional secret of at least 32 characters; otherwise generated |
| `PRECEDENT_BIND` / `PRECEDENT_PORT` | `127.0.0.1` / `8000` |
| `PRECEDENT_CORS_ORIGINS` | Exact localhost origins on 5173 and 8000, comma-separated |
| `PRECEDENT_ALLOWED_HOSTS` | `localhost,127.0.0.1,[::1]`; add backend domain when hosting |
| `GEMINI_API_KEY` | Required for new Gemini responses; free-tier project only |
| `PRECEDENT_AI` | Defaults to enabled; `0` explicitly selects basic-only mode |
| `GITHUB_TOKEN` | Optional server-side GitHub credential |

Hooks outside the repository Git directory are rejected by the web endpoint
because they can be shared. The CLI retains support for custom hook paths.
Explicit chaining preserves existing hooks. `PRECEDENT_SKIP=1` remains a local
Git-push override; it is not an API authentication bypass.

## Hosting limits

Run **one Uvicorn worker**. Locks and the two-thread job executor are in-process;
SQLite is not a distributed job queue. Do not start multiple servers against the
same state directory or modify the same Git index concurrently via another app.
Graceful shutdown waits for jobs; forced shutdown requires resubmitting jobs
marked interrupted at restart.

For trusted hosting: install Python/Git, persist repository and state folders,
configure roots/token/hosts/origins, then run `precedent-server` behind an HTTPS
reverse proxy with request/time limits. Use `PRECEDENT_BIND=0.0.0.0` only where
needed behind that network boundary. Static hosting cannot execute Python/Git.

An HTTPS website calling a local HTTP API may encounter mixed-content or
private-network browser restrictions. Local frontend plus local API is the
development arrangement; production companion access requires suitable secure
transport or desktop integration.

No arbitrary command endpoint, filesystem browser, automatic cloning, OAuth,
user accounts, remote push or tenant isolation is added. Registered repositories
must be trusted: Git configuration/filters and chained hooks can execute local
code. This service is not a sandbox for untrusted repositories.

## Verification and dependencies

Run `python -m pytest -q` with `[web,dev]` installed. Core regressions remain;
Gemini provider tests use mocked transport. Web tests skip
if optional web dependencies are absent. Live Gemini inference needs your key;
Windows/macOS execution remains unverified in this environment.

Official API references:
- https://fastapi.tiangolo.com/tutorial/security/first-steps/
- https://fastapi.tiangolo.com/tutorial/cors/

Additional credits: FastAPI (MIT), Starlette (BSD-3-Clause), Pydantic (MIT),
Uvicorn (BSD-3-Clause), HTTPX (BSD-3-Clause, tests), and transitive dependencies.

## Shared AI response contract

All four AI actions (`check`, `why`, `forecast`, `commit-message`) return an `ai`
object containing `status`, `reason`, `provider`, `model`, `text`, `citations`, and
`cached`. Additional diagnostic fields may appear on successful generation.

| Frontend label | Condition |
| --- | --- |
| Generated | `status == "completed"` and `cached == false` |
| Cached AI result | `status == "completed"` and `cached == true` |
| Unavailable — basic output | `status == "unavailable"`; display `reason` |
| Blocked — basic output | `status == "blocked"`; do not submit the data through another route |
| Basic-only mode | `status == "disabled"` |
| No changes to analyze | `status == "not_applicable"` |

`ai.text` is null outside completed results; `citations` is then empty and `cached`
is false. `why.explanation` and `commit-message.message` may contain basic fallback
text, so check `ai.status`/`mode` before calling that text AI-generated. Forecast
has no GREEN verdict: empty findings are not a claim of complete analysis. Only
check returns a combined verdict, with an additional YELLOW coverage finding when
AI is unavailable or blocked. Explicit basic-only mode may pass deterministic
checks; show its disabled status alongside that verdict.

`GET R/status` returns AI configuration, not an inference result: `enabled`,
`key_configured`, `provider`, `model`, and billing limitations. Neither enabled
nor key_configured proves that inference works. HTTP errors have no AI result:
render an error state, never GREEN. A generated answer does not authorize a push.

The application does not load `.env`. Export variables before starting the backend
and restart it after changing them. Install server and test dependencies with
`python -m pip install -e '.[web,terminal,dev]'`.
