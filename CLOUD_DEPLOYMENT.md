# NEXUS cloud backend for a Vercel frontend

Use `precedent.cloud.server:create_app`. **Do not deploy the local companion
`precedent.web.server` as the public API.** The two services deliberately expose
different contracts. The existing `frontend/src/api.js` and UI still implement the
local companion contract; pointing their backend URL at this cloud service is not
sufficient. Use `examples/cloud-client.mjs` and the integration changes below.

## Architecture and authentication

Vercel serves the frontend and proxies `/api/cloud/*` to a dedicated Linux Python
container. GitHub OAuth authorization-code flow uses S256 PKCE, a random,
browser-bound, single-use state (10 minutes), and a fixed callback. A successful
login rotates this user's sessions and issues an opaque 8-hour session in a
Secure, HttpOnly, host-only SameSite=Lax cookie. PostgreSQL stores only its hash.
`auth/me` exposes identity and a CSRF value, never the GitHub access token.
Mutations require both the exact frontend Origin and `X-CSRF-Token`.

GitHub credentials are encrypted with Fernet in PostgreSQL. Every analysis,
status and history request verifies local ownership and current GitHub access
using that user's credential. Registering a guessed repository ID cannot bypass
membership checks. The legacy shared bearer token is not accepted.

This version uses a **GitHub OAuth App**, requesting `read:user repo`. GitHub's
`repo` OAuth scope is broad and includes write privileges even though NEXUS
implements read operations only. The picker limits NEXUS use, not GitHub's grant.
For installation-level least-privilege access, a future GitHub App migration is
recommended; do not describe this OAuth grant as read-only or repository-scoped.
Organization SSO/app policies may block access; the API fails closed.

## 1. Provision PostgreSQL and backend secrets

Use managed PostgreSQL with TLS, backups and a dedicated application database/user.
Run the migration using a separate migration credential if the runtime role is
restricted. No production values belong in committed files or frontend env vars.
Set these in the **backend hosting dashboard's secret environment**:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | Provider PostgreSQL URI with TLS (`sslmode=verify-full` with provider CA, or the provider's documented secure TLS configuration) |
| `NEXUS_FRONTEND_ORIGIN` | **Your exact** `https://your-production-site.vercel.app`, no trailing slash |
| `NEXUS_API_ORIGIN` | Exact HTTPS origin of the backend, no trailing slash |
| `GITHUB_CLIENT_ID` | GitHub OAuth App client ID |
| `GITHUB_CLIENT_SECRET` | GitHub OAuth App client secret |
| `NEXUS_ENCRYPTION_KEY` | New Fernet key generated below; keep in secret manager |
| `GEMINI_API_KEY` | Backend-only Gemini API key |
| `PRECEDENT_AI` | Optional `0` to explicitly disable AI; otherwise existing Gemini provider is used |

Generate the encryption key locally, then paste it directly into the secret
manager (do not paste it into chat or commit it):

```bash
python -m pip install -e '.[cloud,dev]'
python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/001_cloud.sql
```

The actual Vercel domain was not supplied and was not present in the source.
There is intentionally no permissive CORS fallback. Missing configuration fails
startup; wildcard, HTTP, path-containing and multi-origin values are rejected.
Preview Vercel URLs are not automatically trusted. Use a separate preview backend,
OAuth App and database if preview access is required.

## 2. Configure GitHub OAuth

In GitHub developer settings, create an OAuth App:

- Homepage: your exact Vercel frontend origin.
- Authorization callback: `https://YOUR-EXACT-VERCEL-DOMAIN/api/cloud/auth/callback`.
- Store its client secret only in the backend secret manager.

The browser receives the public client ID, OAuth state and temporary authorization
code as part of the standard redirect flow. It never receives the client secret,
GitHub access token, database URI, encryption key or Gemini key.
Disable query-string logging for the callback at **all proxies**. The included
container disables Uvicorn access logging; platform logs need separate settings.

## 3. Deploy the Python service

Build `Dockerfile.cloud` on a container host with outbound HTTPS to GitHub and
Google and connectivity to PostgreSQL. Expose port 8000 behind HTTPS. Health check:
`GET /health` (also checks database/schema availability).

```bash
docker build -f Dockerfile.cloud -t nexus-cloud .
# Set secrets through the host's secret manager. This command illustrates limits.
docker run --read-only --tmpfs /tmp:rw,nosuid,nodev,noexec,size=512m \
  --memory=1g --cpus=2 --pids-limit=128 -p 8000:8000 \
  --env-file /secure/path/nexus-backend.env nexus-cloud
```

Keep that private env file outside the checkout if using this example. Never
build credentials into the image. Run as the image's non-root user. Set equivalent
memory, CPU, PID, concurrency and scratch-disk limits on managed hosting. GitHub's
reported repository size is an early filter, **not a reliable disk quota**.
Keep Git and the base image patched. No repository code, checkout filters,
submodules or hooks are executed. Bare clones are deleted after every operation;
server-global Git configuration and credentials are excluded from subprocesses.

Multiple processes can share PostgreSQL: advisory transaction locks serialize
operations per user/repository registration. Each operation uses its own clone.
There is no shared local evidence directory, SQLite registry or in-memory job
queue in cloud mode. Use a direct/session-capable DB endpoint that supports normal
transactions (not an HTTP-only database API).

## 4. Vercel rewrite and frontend integration

Add this rewrite **before any SPA fallback** in the Vercel frontend project's
`vercel.json`, replacing the backend hostname with the real one:

```json
{
  "rewrites": [
    { "source": "/api/cloud/:path*", "destination": "https://YOUR-BACKEND-DOMAIN/api/cloud/:path*" }
  ]
}
```

The rewrite contains a public URL, not a credential. The callback and browser
requests stay on the frontend origin so cookies are not third-party cookies.
Do not use `fetch` directly to an unrelated backend domain with this cookie design.
Do not forward or manufacture an Origin header from arbitrary untrusted clients.

Use `examples/cloud-client.mjs`:

```javascript
const api = new NexusCloudAPI();
// Login button: api.login(); navigates to GitHub.
const user = await api.me(); // On page load; 401 means show Sign in.
const available = await api.available(); // Follow next_page for more repositories.
const selected = await api.register(available.repositories[0].github_id);
await api.analyze(selected.id, 'ingest', {limit: 5, refresh: false});
const report = await api.analyze(selected.id, 'check', {base: 'main', tip: 'feature'});
const message = await api.analyze(selected.id, 'commit-message', {base: 'main', tip: 'feature'});
```

Required UI changes:

1. Replace API-token/backend-URL setup with GitHub sign-in and sign-out.
2. Replace the local path field with the paginated GitHub repository picker.
3. Replace staged-change selection with explicit **base and tip** revisions.
4. Call `/api/cloud` routes through the supplied client; keep CSRF only in memory.
5. Label cloud checks advisory. Hide/disable staging and hooks with a local-companion explanation.
6. Use durable per-repository history, not shared browser storage.
7. Preserve existing AI status labels: completed, blocked, unavailable, disabled,
   not_applicable. An HTTP error is never a GREEN result. Render all evidence and
   generated text as text; allowlist external GitHub links before making them clickable.

Do not place any secret in `VITE_*`, `NEXT_PUBLIC_*`, browser storage, URLs or source.
No shared API bearer token is needed in cloud mode.

## Cloud API contract

All routes below have prefix `/api/cloud`. Except OAuth entry/callback, they need
the session cookie. All POST/DELETE requests also need exact Origin and CSRF.

| Method and route | Request / behavior |
| --- | --- |
| GET `/auth/login` | Navigate here to sign in |
| GET `/auth/callback` | OAuth only; fixed redirect back to frontend |
| GET `/auth/me` | `{id, login, csrf_token}` |
| POST `/auth/logout` | Delete current session |
| DELETE `/account` | Delete identity, stored credential, sessions, repositories, evidence and reports; also revoke grant in GitHub Settings |
| GET `/capabilities` | Available analysis and explicit local-only operations |
| GET `/github/repositories?page=1` | 50 accessible repositories/page; `next_page` |
| GET `/repositories` | Only current user's selections |
| POST `/repositories` | `{github_id: number}`; idempotent selection, returns opaque `id` |
| GET `/repositories/{id}/status` | Rechecks GitHub access; repository and AI configuration |
| POST `/repositories/{id}/ingest` | `{limit: 1..50, refresh: false}`; synchronous bounded evidence ingestion |
| POST `/repositories/{id}/check` | `{base,tip}`; every outgoing commit, including later-deleted secrets |
| POST `/repositories/{id}/secrets` | `{base,tip}`; every outgoing commit, findings redacted |
| POST `/repositories/{id}/forecast` | `{base,tip}`; net diff plus sampled historical review evidence |
| POST `/repositories/{id}/commit-message` | `{base,tip}`; net-diff suggestion, never commits or pushes |
| POST `/repositories/{id}/why` | `{path,line,ref}`; blame plus stored evidence |
| GET `/repositories/{id}/history` | Latest 50 persisted reports; optional `before` timestamp cursor |
| POST `/repositories/{id}/hooks` or `/stage` | 409: local companion required |

Check/secret ranges are capped at 100 commits; changed content at 500 file-change
records/20,000 lines, Git command output at 8 MiB, stored evidence at 32 MiB.
Ingestion uses at most 250 GitHub requests and 10 pages per collection. Per-user
DB-backed limits: 30 analysis operations/hour and 200 repository API reads/hour;
OAuth entry has a global 300/minute limit. Add per-IP edge rate limiting for public
login/health traffic; application limits are not DDoS protection.

## Persistence, failures and operational limits

Users, encrypted OAuth credentials, session hashes, one-use OAuth state,
repository ownership, encrypted evidence/cache snapshots and redacted reports
persist in PostgreSQL. The unchanged analysis engine uses **temporary SQLite**
inside a disposable clone for its relational evidence queries; its encrypted
snapshot is loaded from and saved back to PostgreSQL transactionally. This is a
compatibility bridge, not a local durable database or a normalized scalable
PostgreSQL evidence schema. Successful requests survive host restart/redeployment.
Failure rolls back evidence/report updates; retry ingestion after a failure.

Ingestion and analyses are synchronous in this release. Use small bounded samples
(start with limit 5). Vercel/reverse-proxy request limits can interrupt slow work;
a browser timeout is an error, not completion. A server operation may still finish:
check status/history before retrying. Large-repository/background workloads need
a durable job worker before scaling. No async jobs endpoint is claimed here.

The cloud service reads branch commits, not laptop staged or unstaged changes.
Git hooks, pre-push blocking, prepare-commit-msg hooks and staging remain in the
existing local CLI/companion only. Historical evidence is bounded and incomplete;
Gemini remains advisory. Existing provider secret-scanning and redaction are
preserved, but secret detection is heuristic. Get consent before sending private
code to Gemini and verify your provider's data policy. No live Gemini call was
performed during this change.

Keep the encryption key backed up separately from the database. Losing/changing it
without re-encrypting stored tokens and snapshots makes them unreadable. This
release has one key; a rotation needs an explicit maintenance migration, not simply
changing the env var. Backups must follow your deletion/retention policy. Set
retention for reports/rate-limit rows with a scheduled database maintenance task.
No automatic import of the legacy shared SQLite store: users sign in, select and
re-ingest authorized repositories to avoid assigning shared private data to the
wrong tenant.

## Verification

```bash
python -m pip install -e '.[cloud,web,dev]'
python -m pytest -q
# Use an isolated test PostgreSQL database. Tests create/drop their own schema.
export NEXUS_TEST_DATABASE_URL='postgresql://TEST_USER:TEST_PASSWORD@localhost/nexus_test'
python -m pytest tests/test_cloud_backend.py -q
```

`.github/workflows/cloud-tests.yml` runs the full suite with PostgreSQL 16. Tests
cover exact CORS, auth/CSRF, OAuth state replay and PKCE, expired/revoked sessions,
repository membership and tenant isolation, revoked GitHub access, durable report
and encrypted evidence persistence across app instances, local-only endpoints,
limits and existing analysis regressions. GitHub and Gemini are mocked; live OAuth,
provider credentials, deployment and browser cookie/proxy behavior need a final
smoke test with your domains. Without a test database, PostgreSQL integration
cases are explicitly skipped, not reported as verified.

Before enabling users: sign in through Vercel, select a private test repo, ingest,
check/forecast/why/generate a message, reload history after backend restart, verify
a second GitHub account cannot access the first account's ID, revoke GitHub access
and verify analysis/history fail, then sign out and verify 401.

OAuth protocol reference: https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/authorizing-oauth-apps

## Validation recorded for this package

70 tests passed, including the four database integration scenarios, against
PGlite's PostgreSQL engine via its wire-protocol server. Native PostgreSQL 16 CI
is configured but was not run here. This validates SQL/application behavior, not
native PostgreSQL multi-process concurrency or a live cloud deployment.
`git diff --check`, Python compilation and JavaScript syntax checks also passed.
The connected GitHub account has no push permission for this repository; changes
are provided as a package and patch rather than an upstream pull request.
