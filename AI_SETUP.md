# AI enabled by default — version 0.3.1

The backend now calls Gemini automatically for line-history explanations,
commit-message generation, combined code-review interpretation and CLI/web review
forecast interpretation. This is generation from evidence and changes, not the
previous candidate selector. The only model is `gemini-3.5-flash-lite`.

## Free-tier requirement

1. Open https://aistudio.google.com/ and create/select a project with Free-tier access.
2. Create a Gemini API key in that project.
3. Check its active quota and eligibility in AI Studio. Do not enable paid billing
   or use a paid project's key if you require zero API charges.
4. Keep the key on the backend machine. Never put it into frontend JavaScript,
   your Git repository, a URL, a screenshot, or chat.

The model is listed with free-tier text input/output at implementation time.
Availability and quotas depend on the account/project. Free usage is limited;
the code cannot infer billing status from an API key. The same endpoint can bill
a paid project. No application-only setting can guarantee zero cost with the
wrong project's key. There is no paid-provider fallback, no model auto-upgrade,
no search-grounding tool, and no automatic retry loop. A quota failure remains
visible; the application does not upgrade billing or switch models.

## Windows PowerShell: start the web backend

From the extracted `precedent-bouncer` folder:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[web,terminal,dev]"
$env:GEMINI_API_KEY = "paste-your-free-tier-project-key-here"
$env:PRECEDENT_REPO_ROOTS = (Get-Location).Path
Remove-Item Env:PRECEDENT_AI -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m precedent.web.server
```

`PRECEDENT_AI` defaults to enabled. Removing a previous `0` setting restores the
default. The Gemini key is separate from the local web API bearer token. Read
`WEB_BACKEND.md` to authorize `/docs`, register a repository and call endpoints.
Environment changes require restarting the backend from that same terminal.
The supplied `.env.example` is a reference, not an automatically loaded file.

Linux/macOS: install the same extras, `export GEMINI_API_KEY='your-key'`, set
`PRECEDENT_REPO_ROOTS`, and run `precedent-server`.

## Verify real AI usage

With a registered repository and cached evidence, call `why` using an ingested
committed line. A successful result includes:

```json
{
  "mode": "gemini-generated",
  "ai": {
    "status": "completed",
    "provider": "gemini",
    "model": "gemini-3.5-flash-lite",
    "cached": false
  }
}
```

The code also returns generated text and source citations. Status showing
`enabled: true` only confirms configuration; it does not prove inference worked.
`key_configured: true` only confirms presence, not key validity or free quota.

Successful results are cached locally for 24 hours with exact prompt/model/source
identity. A reused response reports `cached: true` and `gemini-generated-cached`.
It is a previously generated result, not new inference. API keys and raw prompts
are not persisted in the AI cache; generated output and source excerpts are.

## Demonstrate AI with the synthetic fixture

Create a fresh demo with `scripts/create_demo.py web-demo-ai`, register that path,
and call `why` for `src/parser.py:2`. Historical evidence is synthetic and clearly
labeled, but the configured Gemini request and generated explanation are real.

The fixture intentionally stages a fake credential. Combined check and commit
generation **block cloud submission** until that credential is removed, even
though it is fake. To demonstrate AI review of the guard deletion:

```powershell
cd web-demo-ai
git rm -f config.py
```

Keep the guard deletion staged. Then call check or commit-message again. Check
should keep the deterministic RED safeguard warning and display the model's
separate interpretation. Never claim the synthetic history is a real upstream PR.

## Availability and honest fallback

| AI result | Meaning / action |
| --- | --- |
| `completed` | Generated response passed structural/reference validation |
| `unavailable: missing_api_key` | Set GEMINI_API_KEY on the backend and restart |
| `unavailable: quota_or_rate_limit` | Provider returned 429; wait/check free quota, no automatic paid fallback |
| `unavailable: invalid_api_key` | Provider returned 401; replace the backend key |
| `unavailable: invalid_request_or_key` | Provider returned 400; check key validity and request/model compatibility |
| `unavailable: project_access_denied` | Verify key/project access and free-tier eligibility |
| `unavailable: model_unavailable` | Provider did not serve the configured model; no automatic model switch |
| `unavailable: network_or_timeout` | Check connectivity; requests time out after 30 seconds |
| `unavailable: context_too_large` | Request exceeds 30,000 serialized characters; analyze a smaller change |
| `unavailable: invalid_output` or citation error | Model result rejected; basic results remain explicitly labeled |
| `blocked: suspected_secret_in_changes` | Remove suspected credentials before cloud analysis; inspect false positives locally |
| `blocked: suspected_secret_in_context` | Remove suspected secrets from history/context; no request or cache lookup occurs |
| `disabled` | PRECEDENT_AI=0 was explicitly set |
| `not_applicable` | No changes to analyze |

Unknown historical evidence prevents a generated `why` explanation. The app
does not invent history. A commit message can still be generated from a diff
without history, with no invented issue references.

Changed-code checks with unavailable/blocked AI add a YELLOW coverage warning.
They cannot silently report GREEN. RED findings still block pushes. YELLOW still
allows a push with warnings, preserving the existing hook policy. Explicitly
disabled AI is basic-only mode; frontend labels must reflect that. With no changes,
AI is not applicable and a clean result is possible without a request.

## Data and interpretation limits

Google receives sanitized relevant code changes, historical messages and evidence.
This replaces the prior entirely local inference behavior. Free-tier data may be
used to improve Google's products; use public/synthetic repositories for the demo.
Suspected secrets in either added or removed lines block sending those changes.
Raw historical content is also scanned before truncation; any suspected secret blocks the entire AI submission. Historical output is redacted separately. Secret detection is heuristic, so
review what repositories you expose; it does not guarantee every credential is found.

The request includes up to 12 unique evidence records, at most 1,000 characters
each. The model returns generated prose and E identifiers. References are checked
against the supplied records; source numbers/URLs are supplied by the backend.
This does not prove the prose is correct. Interpretations are advisory and cannot
downgrade a deterministic RED risk. Model output is never executed as code.

`PRECEDENT_MODEL` is not read. Gemini is proprietary: this version does not on its own satisfy an
open-weight-model prize requirement.

## Verification

Provider tests mock successful/failed Gemini HTTP responses. They validate
default enablement, payloads, caching, citations, quotas, secret blocking and
explicit unavailable states. Live inference cannot be claimed until a real key
and eligible project are used. Run `python -m pytest -q` after installing extras.

Provider references checked during implementation:
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/gemini-api/docs/rate-limits
- https://ai.google.dev/gemini-api/docs/api-key
- https://ai.google.dev/api/generate-content

## Protocol verified against Google documentation, 31 October 2026

- Model: `gemini-3.5-flash-lite`, listed as stable with structured-output support.
- POST `https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent`.
- Authentication: `x-goog-api-key` header populated exclusively from the backend
  process environment. The key is never placed in the URL or response.
- JSON body: `systemInstruction`, `contents` (user text parts), and
  `generationConfig`. Structured JSON uses `responseFormat.text.mimeType` =
  `APPLICATION_JSON` and `responseFormat.text.schema`, rather than deprecated
  `responseSchema`. The schema requires `text` and `evidence_ids`.
- Response: the first `candidates` entry must have `finishReason: STOP`; non-thought
  `content.parts[].text` values are combined and parsed as JSON. Schema/type/length
  and supplied evidence IDs are validated locally; URLs and issue numbers invented
  in prose are rejected. This validates references, not factual accuracy.
- Timeout: 30-second socket timeout; at most 262,144 response bytes and 30,000
  serialized prompt characters. No retries, redirects, tools, or alternate providers.
- A 429 means quota OR rate limiting, not proof that a free tier was exhausted.
  Error response bodies are never returned or logged by the provider.
- The 24-hour cache is local SQLite, keyed by model, schema revision, system prompt,
  context and source identity. Malformed/expired entries are ignored. It is not
  Google's paid context-caching service. Keep the database private.
- AI runs by default. `PRECEDENT_AI=0` disables it even for cached explanations.
  No-change check/forecast/commit-message returns `not_applicable`; `why` with no
  evidence returns `unavailable` unless AI is explicitly disabled.

Official sources:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.5-flash-lite
- https://ai.google.dev/gemini-api/docs/pricing
- https://ai.google.dev/api
- https://ai.google.dev/api/generate-content
- https://ai.google.dev/gemini-api/docs/generate-content/structured-output

These docs confirm protocol and published model support, not your account access.
No live Google request was made during this update.
