# Three-minute offline demonstration

Run the setup once before presenting, in a shell with the package installed.
The fixture intentionally uses synthetic GitHub data, clearly labeled in output.
The Git commits and push-blocking behavior are real.

```bash
python scripts/create_demo.py demo-workspace
cd demo-workspace
git init --bare ../demo-remote.git
git remote add origin ../demo-remote.git
git push origin HEAD:refs/heads/main  # establish clean baseline before installing hooks
precedent install-hooks
```

1. **0:00–0:15:** “Developers can see what code does, but its reasons are buried
   in history. This demo uses synthetic review evidence and actual Git operations.”
2. **0:15–0:55:** `precedent why src/parser.py:2`. Show the blamed commit and cached
   empty-input history. Explain that line numbers refer to HEAD, not unstaged files.
3. **0:55–1:35:** `precedent check`. Guard deletion is RED; missing tests show
   3 of 4 cached PRs; the fake credential is detected without AI. No network needed.
4. **1:35–2:05:** `git push origin HEAD:refs/heads/demo-risk`. The new branch update
   invokes pre-push and the staged guard deletion/credential block it. The tool
   additionally tests committed outgoing history, as documented in validation.
5. **2:05–2:40:** Fix the staged change and preview the history-matching message:

```bash
git restore --source=HEAD --staged --worktree src/parser.py
git rm -f config.py  # discard the staged synthetic demonstration credential
mkdir -p tests
printf 'from src.parser import parse\n\ndef test_parse():\n    assert parse("abc") == "a"\n' > tests/test_parser.py
git add tests
precedent check
precedent commit-message
git commit -m 'test(parser): cover valid input'
git push origin HEAD:refs/heads/main
```

6. **2:40–3:00:** “Facts and verdicts are deterministic. The optional local model
   selects grounded wording. Missing evidence is explicitly shown, and everything
   required for this demo is cached.”

The real `prepare-commit-msg` demonstration is optional: use `git commit` without
`-m`, then show the prefilled editor. Avoid spending stage time in an unfamiliar
editor. Rehearse with a fresh demo directory; the setup refuses overwrites.

Judge questions:
- **Can it prove a change is wrong?** No. Guard and history heuristics prioritize review.
- **Is 3/4 representative?** No. It is the cached sample, disclosed in the warning.
- **Why not ask an LLM?** A model cannot establish historical facts from missing evidence.
- **Does it read the entire repository history?** Bounded ingestion; push scanning is a separate scope.
- **Are the examples real PRs?** The fixture is synthetic. Real ingestion uses GitHub REST and actual URLs.
- **Can developers bypass it?** Yes; local hooks are advisory controls, not server enforcement.
