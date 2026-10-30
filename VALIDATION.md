# Validation record

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
