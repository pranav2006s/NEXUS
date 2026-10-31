# NEXUS Frontend

A separate React + Vite developer console for the existing [NEXUS](https://github.com/pranav2006s/NEXUS) FastAPI backend (inspected October 31, 2026). This frontend does **not** edit or replace backend logic.

## Requirements

- Node.js 20.19+ or 22.12+ (for Vite 6 compatibility).
- Existing NEXUS Python backend running at `http://127.0.0.1:8000`.
- A private bearer token from the backend's `~/.precedent-web/api-token` or `PRECEDENT_API_TOKEN`.

## Run frontend

```bash
cd nexus-frontend
npm install
npm run dev
```

Open <http://127.0.0.1:5173>. Enter the backend URL and its bearer token. The token lives in React memory only and disappears on refresh, disconnect, or closing the tab. It is not compiled into the bundle or stored in localStorage/sessionStorage.

## Run backend (Windows PowerShell example)

From the root of the *separate NEXUS backend repository*:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web,terminal,dev]"
$env:GEMINI_API_KEY = "<your-Gemini-key>"
$env:PRECEDENT_REPO_ROOTS = (Get-Location).Path
$env:PRECEDENT_CORS_ORIGINS = "http://127.0.0.1:5173,http://localhost:5173"
.\.venv\Scripts\python.exe -m precedent.web.server
```

The example key placeholder belongs only to the **backend shell**, never the browser. The backend does not auto-load `.env`; set environment variables before starting it.

Read the bearer token in another PowerShell session:

```powershell
Get-Content "$HOME\.precedent-web\api-token"
```

Go to NEXUS backend's `WEB_BACKEND.md` for complete backend configuration.

### Demo fixture

```powershell
.\.venv\Scripts\python.exe scripts\create_demo.py demo-workspace
```

Then register the **absolute** path to `demo-workspace` in the frontend. It must be inside `PRECEDENT_REPO_ROOTS`. The fixture is synthetic and intentionally contains a risky staged change, so expected findings are not real GitHub evidence. Do not ingest live GitHub history into this synthetic demo.

## Features

- Live connection via `GET /api/v1/repositories` using bearer-token authorization.
- Register/select repository; show status, ingestion coverage, AI configuration, and staged paths.
- Stage named repository-relative paths.
- Check staged changes or a Git commit range; display actual RED/YELLOW/GREEN verdict, findings, push allowance, analysis status, and Gemini status.
- Explain historical code lines with `why` and cached evidence.
- Generate a review forecast, commit message, or secret scan.
- Ingest GitHub history asynchronously with job-status polling.
- Install backend-local pre-push and prepare-commit-msg hooks, with explicit confirmation.
- Responsive desktop/mobile layout.

## Security and scope

- **Do not deploy this as an open, multi-user web service.** NEXUS currently uses a single shared bearer token that grants access to all registered repositories; it requires a separate per-user identity, authorization, and isolation layer before public deployment.
- `GEMINI_API_KEY` and `GITHUB_TOKEN` belong exclusively to the Python backend.
- Server responses are rendered as React text nodes, not HTML, to avoid unsafe rendering of repository text.
- The API only sees Git repositories on the machine running the Python backend. A hosted browser cannot directly read files on each visitor's laptop or install hooks on the visitor's machine.
- A RED result may come back with HTTP 200; results are driven by `verdict`, not HTTP status. On an API error, the frontend does not claim GREEN.
- Git hooks can be bypassed. AI output is advisory and not a guarantee of correctness or approval.
- Only simulated/HTTP-mocked unit tests can prove compatibility without a live backend and Gemini key. Integration tests were not run in this environment.

## Repo integration

Copy `nexus-frontend/` into the root of your NEXUS checkout, then run `npm install && npm run dev` inside it. The backend code stays untouched.
