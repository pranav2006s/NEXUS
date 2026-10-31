# Precedent Bouncer — Frontend Web Application

A modern, responsive, developer-oriented code intelligence dashboard for **Precedent Bouncer**, an AI-powered, history-aware Git protection and productivity platform.

Built with **React**, **Vite**, **TypeScript**, **Tailwind CSS**, and **Recharts**.

---

## 1. Quick Start

### Prerequisites
- Node.js (v18+)
- Python 3.11+ (for the Precedent Bouncer FastAPI backend)

### Installation
From the `frontend` directory:
```bash
npm install
```

### Development Server
```bash
npm run dev
```
The application runs by default at `http://localhost:5173`.

### Production Build
```bash
npm run build
npm run preview
```

---

## 2. Connecting to the Backend

The frontend connects to the Python FastAPI companion server running at `http://127.0.0.1:8000`.

### Running the Python Backend
In PowerShell from the repository root:
```powershell
$env:PRECEDENT_REPO_ROOTS = (Resolve-Path .).Path
$env:PRECEDENT_WEB_STATE = (Resolve-Path .\.precedent-web).Path
$env:PRECEDENT_CORS_ORIGINS = "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:8000,http://localhost:8000"
$env:PRECEDENT_AI = "0" # Optional: set to 1 if local Ollama model (gemma3:4b) is active
.\NEXUS-main\.venv\Scripts\python.exe -m uvicorn precedent.web.server:create_app --factory --host 127.0.0.1 --port 8000
```

### Supplying the Bearer API Token
1. Open the Precedent Bouncer Web UI (`http://localhost:5173`).
2. Navigate to **Settings** (`/settings`).
3. Enter your API Token (generated in `.precedent-web/api-token` or configured via `PRECEDENT_API_TOKEN`).
4. Click **Save & Verify**. The status badge in the sidebar will switch to **Online**.

---

## 3. Dedicated Pages & Feature Tour

| Page | Path | Description |
| --- | --- | --- |
| **Dashboard** | `/` | Repository health overview, risk distribution chart, metric cards, recent analyses, quick actions. |
| **Fence Check** | `/fence-check` | Core feature: evaluates staged diffs & outgoing commits against historical bug justifications. Displays code diffs, blamed commits, PR/issue links, and recommendations. |
| **Secret Scanner** | `/secret-scanner` | Credential interception for AWS access keys, GitHub tokens, and private keys. All secrets redacted; remediation guidance provided. |
| **Review Forecast** | `/review-forecast` | Empirical radar & bar charts of recurring maintainer expectations (tests, error handling, performance, security). |
| **Precedent Explorer** | `/precedent-explorer` | Code investigation search (`file.py:line`) explaining why code exists, linking blamed commits with historical issues and PR timeline. |
| **Commit Generator** | `/commit-generator` | Conventional commit message suggestion with issue backlinks and interactive editor. |
| **Repositories** | `/repositories` | Register local repository roots inside `PRECEDENT_REPO_ROOTS` and trigger GitHub evidence ingestion. |
| **Analysis History** | `/history` | Search, filter by verdict, view past reports, and export history as JSON. |
| **Settings** | `/settings` | Backend URL, API bearer token, Local AI Ollama status, GitHub token status, and theme toggle. |

---

## 4. Design System Tokens

- **Background:** Dark charcoal (`#090d16`)
- **Surfaces:** Deep navy (`#0f172a`, `#111c33`)
- **Borders:** Subtle slate (`#1e293b`)
- **Accents:** Electric cyan (`#38bdf8`) & Royal blue (`#2563eb`)
- **Verdict Indicators:**
  - `RED`: Confirmed critical risk or secret detected (`#ef4444`)
  - `YELLOW`: Caution, missing tests, or incomplete coverage (`#f59e0b`)
  - `GREEN`: No significant historical invariant violated (`#10b981`)
- **Typography:** Inter (Sans-serif UI) & JetBrains Mono (File paths, hashes, code snippets, diffs)
