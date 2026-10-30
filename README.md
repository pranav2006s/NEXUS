# Precedent Bouncer

**Version 0.3 enables Gemini AI by default and retains the website JSON API.** See `WEB_BACKEND.md` for API setup,
all feature endpoints, authentication, background ingestion, and the JavaScript
frontend client. Start with `AI_SETUP.md` to configure a free-tier Gemini key.
The original CLI workflow below remains available.

A local Python CLI that connects changed code to cached GitHub history and flags
possible safeguard removals, credential leaks, and recurring review patterns.

**Pitch:** "Linters check whether your code is valid. Precedent Bouncer checks
whether it's welcome." This is a pitch, not a prediction of maintainer approval.

## Quick start

Requires Python 3.11+ and Git. Core commands need no third-party Python packages.

```bash
python -m venv .venv
source .venv/bin/activate             # Windows PowerShell: .venv\Scripts\Activate.ps1
python -m pip install -e '.[terminal,dev]'
precedent --help
python scripts/create_demo.py demo-workspace
cd demo-workspace
precedent why src/parser.py:2
precedent check                       # expected RED, exit 1
precedent commit-message
precedent install-hooks
```

Offline alternative: from the project directory, `python -m precedent --help`.
To use it inside another repository without installing, put the absolute project
directory on `PYTHONPATH`, then run `python -m precedent`. Rich output is optional.
Hooks use the installing Python interpreter and absolute source path: keep both
in place, or reinstall hooks after moving the application/virtual environment.

## Real repository workflow

```bash
cd /path/to/your/existing/repository
# Optional: export GITHUB_TOKEN=... (do not put it in tracked files)
precedent ingest OWNER/REPOSITORY --limit 40
precedent status
git add src/parser.py
precedent ingest OWNER/REPOSITORY --limit 40  # includes blamed staged deletions
precedent check
precedent why src/parser.py:42
precedent install-hooks
```

`ingest` reads GitHub REST API data only; it never creates PRs, issues, or comments.
It fetches a bounded local commit sample plus commits blamed for staged deletions,
associated PRs, their changed files and inline review comments, and explicitly
referenced same-repository closing issues. It paginates, stores ETags, skips
completed commits, and stops with an explicit incomplete state on API failures.
`--refresh` revalidates cached responses and refreshes covered commits.
History may become stale; refresh before the event, then use cached data on stage.
No automatic rate-limit sleep: retry later or use an optional GitHub token.

SQLite lives at the repository's Git directory, `precedent.sqlite3`; it is not
staged by Git. Worktrees get their own evidence databases. The database is bound
to one GitHub repository. A synthetic demo store cannot ingest real history.

## Commands and exit codes

| Command | Behavior |
| --- | --- |
| `precedent ingest OWNER/REPO [--limit N] [--refresh]` | Fetch relevant evidence; needs network |
| `precedent check [--json]` | Analyze staged changes, not unstaged edits |
| `precedent why FILE:LINE [--ref REF] [--json]` | Blame the committed line and show chronological cached evidence |
| `precedent commit-message` | Print a proposed message without changing a commit |
| `precedent install-hooks [--chain-existing]` | Install pre-push and prepare-commit-msg hooks |
| `precedent status` | Display local cache and configuration status |

Exit 0 = GREEN/YELLOW or successful command. Exit 1 = RED gate. Exit 2 = error /
analysis incomplete. YELLOW warnings allow pushes. An execution error blocks the
push. Missing historical coverage is YELLOW, never silently GREEN.
GREEN means no flagged risk in analyzed scope; GREEN findings count is zero
because the tool reports problems rather than manufacturing positive findings.

## Five implemented features

1. **Fence Check:** deleted/modified old lines → blame → commit → cached PR,
   issue and review evidence. Guard-like keywords plus risk-related historical
   language trigger RED when no guard-like replacement appears. Replacement
   guards and weak/missing evidence trigger YELLOW. Findings group by file and
   blamed commit, not individual diff hunk. This is a deliberately simple
   heuristic: it does not prove a safeguard has been weakened. The check also
   requests an AI interpretation of the sanitized diff and available evidence.
   AI cannot override deterministic RED findings.
2. **Secret interception:** added lines checked for AWS/GitHub token shapes,
   private-key headers and quoted credential assignments. High-entropy quoted
   strings produce YELLOW; recognized patterns produce RED. Values are never
   included in findings. Historical text is also redacted at output. False
   positives and false negatives are possible; this is not a full secret scanner.
3. **History-aware commit messages:** majority conventional-commit style and
   capitalization inferred from the last 30 subjects; scope, filenames, action,
   and changes come from the staged diff. Gemini generates a specific subject
   matching the repository history. Verified issue references are appended as
   historical context, never automatically asserted to be fixed. Unavailable AI
   produces a clearly labeled basic template, including in the commit hook.
4. **Review forecast:** distinct PR counts per exact directory, with keyword
   categories for tests, errors, docs, naming, performance and security. A missing
   test warning requires at least three sampled PRs and at least half mentioning
   tests in inline reviews. Test changes anywhere suppress that warning. Counts
   describe sampled mentions, not proven requests or a representative population.
   AI interprets these findings alongside the actual changes in the combined
   check and the web forecast endpoint.
5. **`why`:** commit attribution, timestamp-sorted PR/issue/review evidence,
   source links for real ingested data, and explicit missing-data handling.
   Git blame identifies the last modifying commit, not necessarily the first
   introduction. Synthetic fixtures have no pretend GitHub links. Gemini
   generates a plain-English explanation from supplied cached evidence, with
   validated source identifiers and an explicit AI status.

## Correct pre-push behavior

The hook reads Git's ref updates from stdin and checks **every outgoing commit
patch against every parent**, plus staged changes. This catches a secret added
and removed in successive commits. For new remote branches it conservatively
checks all reachable history, which can be slow and may flag old resolved issues.
Deletion-only pushes have no outgoing commit history. Non-commit tags / missing
remote objects fail explicitly; fetch remote history and retry.

Existing hooks are not overwritten by default. `--chain-existing` renames them
to `.precedent-original` and invokes them first with their original arguments and
stdin. Nonzero exit codes are preserved. Installation honors `core.hooksPath`;
check whether a custom hooks directory is shared across repositories first.

Explicit emergency bypass (does not bypass a chained existing hook):

```bash
PRECEDENT_SKIP=1 git push
```

PowerShell: `$env:PRECEDENT_SKIP='1'; git push; Remove-Item Env:PRECEDENT_SKIP`.
Git hooks are local and bypassable; they are not an enforced server policy.
The prepare-commit-msg hook fills only an empty, source-less message, leaving
`-m`, templates, merge/squash and amend messages untouched. It never auto-commits.

To uninstall, remove only the two files containing the managed-hook marker,
then rename any `.precedent-original` backups back to their original names.

## Default-on Gemini AI

Read `AI_SETUP.md`. Set `GEMINI_API_KEY` on the backend host using a project on
Google's Free tier. No `PRECEDENT_AI=1` switch or Ollama download is required.
The only configured model is `gemini-3.5-flash-lite`, listed with free-tier text
input/output at implementation time. There are no paid-provider/model fallbacks,
search-grounding tools or automatic retries. The API key does not reveal billing
status: a paid project's key can incur charges on the same endpoint. Keep the
project on the Free tier; do not enable paid billing for this setup.

AI generates historical explanations, commit subjects and advisory review text.
Diffs are checked for suspected secrets before cloud inference. Detection blocks
AI submission of those changes; evidence and context are redacted separately.
This is heuristic protection, not a guarantee that every secret is detected.
Sanitized code/history is sent to Google, so this is no longer an entirely local
inference workflow. Use public/synthetic demo repositories; Google's free-tier
terms can permit submitted data to be used to improve its products.

Output is structured and source IDs are validated against supplied evidence;
that does not prove every sentence is factually correct. AI is explicitly labeled
as interpretation. Results are cached in SQLite for 24 hours by model/prompt/
source identity, without storing keys or raw prompts. The timeout is 30 seconds.
Missing keys, exhausted quota or malformed responses are visible as unavailable.
Changed-code checks add a YELLOW AI-coverage warning instead of silently GREEN.
YELLOW still permits pushes, per the original gate policy. Deterministic RED
findings are never downgraded by AI. With no changed code, AI is not applicable.

`PRECEDENT_AI=0` explicitly disables cloud AI for offline/basic-only operation.
Cached results can be reused without a working key if AI remains enabled and the
exact input is unchanged. Changes to prompts or evidence require a new response.
The previous Ollama selector and `PRECEDENT_MODEL` setting are retired in v0.3.

## Architecture / team explanation

| File | Responsibility |
| --- | --- |
| `gitops.py` | Safe argument-array Git calls, staged patches, blame, outgoing history |
| `storage.py` | SQLite documents, associations, cache and coverage |
| `ingestion.py` | GitHub GET requests, pagination, ETags, incremental persistence |
| `analysis.py` | Deterministic fence, secret, forecast and combined verdict rules |
| `ai.py` | Grounded prompts, credential blocking, generation and labeled basic output |
| `cloud_ai.py` | Default-on Gemini adapter, citation validation and response cache |
| `hooks.py` | Hook preservation and commit-message safety |
| `cli.py` | Commands, redacted Rich/plain/JSON output and exit codes |

## Validation and demonstration

```bash
python -m pytest -q
```

Tests use temporary real Git repositories and a local bare remote. API and AI
responses are mocked in unit tests; these tests are not evidence of live service
availability. See `VALIDATION.md` for what was actually run in this build.
See `DEMO.md` for the offline presentation sequence.

Known limits: no semantic analysis, embeddings, AST, AST-based guard matching,
full-history guarantee, rename tracing, unstaged-file checking, binary content
scanning, Git LFS scanning, cross-repository issues, or general PR conversation
ingestion. Shallow clones and inaccessible objects can reduce blame/ingestion
coverage. Large/new branches can be slow. Full Git history is not claimed.

## Hackathon / open source

Built from the supplied brief with ChatGPT/Codex AI coding assistance. Team
members must review and understand it. Preserve actual Git timestamps; do not
claim the build occurred during the event unless its rules and timing support it.
Confirm Theme 03 alignment, Round 1 continuity, and prize eligibility with the
organizer; this project alone does not prove eligibility. Do not claim "first" or
guaranteed maintainer acceptance.

License: MIT. Credits: Python standard library (PSF), Git (GPL-2.0), Rich (MIT,
optional), pytest (MIT, development), setuptools (MIT, packaging), and Google's
Gemini API (service terms apply; no model weights bundled).
GitHub evidence remains attributable to its original repository authors and URLs.
Gemini is proprietary; this version alone does not demonstrate an open-weight
AI challenge entry. No code was copied from an external application repository. Synthetic examples
were generated for this project. No real credentials are included.

To contribute, create a focused change and add a regression test for behavior
changes. Run pytest before submitting. Do not publish packages or contact upstream
maintainers for demo purposes. Create a public GitHub repository and push this
project only when you are ready; no public repository is created automatically.
