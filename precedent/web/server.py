"""Run with precedent-server or uvicorn precedent.web.server:create_app --factory."""
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path, PurePosixPath
from typing import Literal
import hmac
import os
import secrets
import sqlite3
import subprocess

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .. import __version__
from ..ai import commit_message_result, explain_result, review_changes
from ..cloud_ai import settings as ai_settings
from ..analysis import check, forecast, secrets as scan_secrets
from ..cli import safe
from ..gitops import GitError, Repo
from ..hooks import hook_dir, install
from ..ingestion import APIError, ingest
from ..storage import Store
from .state import State


def clean(value):
    if isinstance(value, str): return safe(value)
    if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)): return [clean(v) for v in value]
    return value


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Register(Body):
    path: str = Field(min_length=1, max_length=4096)


class Ingest(Body):
    repository: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    limit: int = Field(default=40, ge=1, le=1000)
    refresh: bool = False


class Check(Body):
    scope: Literal["staged", "commits"] = "staged"
    base: str | None = Field(default=None, max_length=200)
    tip: str = Field(default="HEAD", max_length=200)


class Why(Body):
    path: str = Field(min_length=1, max_length=4096)
    line: int = Field(ge=1)
    ref: str = Field(default="HEAD", min_length=1, max_length=200)


class Hooks(Body):
    chain_existing: bool = False


class Stage(Body):
    paths: list[str] = Field(min_length=1, max_length=100)


def create_app(*, roots=None, state_dir=None, token=None, origins=None, hosts=None):
    """Explicit kwargs support tests. Deployment uses documented environment variables."""
    roots = roots if roots is not None else os.environ.get("PRECEDENT_REPO_ROOTS", "").split(os.pathsep)
    roots = [Path(p).expanduser().resolve() for p in roots if str(p)]
    if not roots:
        raise RuntimeError("Set PRECEDENT_REPO_ROOTS to the trusted folder containing your repositories.")
    state_dir = Path(state_dir or os.environ.get("PRECEDENT_WEB_STATE", str(Path.home() / ".precedent-web"))).expanduser().resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    token = token or os.environ.get("PRECEDENT_API_TOKEN")
    if not token:
        token_path = state_dir / "api-token"
        if not token_path.exists():
            try:
                fd = os.open(token_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                with os.fdopen(fd, "w") as stream: stream.write(secrets.token_urlsafe(32))
            except FileExistsError:
                pass
        token = token_path.read_text().strip()
    if len(token) < 32:
        raise RuntimeError("PRECEDENT_API_TOKEN must contain at least 32 characters.")
    origins = origins if origins is not None else [s.strip() for s in os.environ.get("PRECEDENT_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173,http://127.0.0.1:8000,http://localhost:8000").split(",") if s.strip()]
    if "*" in origins: raise RuntimeError("Specify exact browser origins, not '*'.")
    state = State(state_dir)

    @asynccontextmanager
    async def lifespan(app):
        yield
        state.pool.shutdown(wait=True, cancel_futures=False)

    bearer = HTTPBearer(auto_error=False)
    def authenticate(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not hmac.compare_digest(credentials.credentials.encode(), token.encode()):
            raise HTTPException(401, "Valid bearer token required", headers={"WWW-Authenticate": "Bearer"})

    app = FastAPI(title="Precedent Bouncer API", version=__version__, lifespan=lifespan,
                  description="Single-user web adapter. Evidence-backed checks and default-on Gemini AI.")
    app.state.backend = state
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts or os.environ.get("PRECEDENT_ALLOWED_HOSTS", "localhost,127.0.0.1,[::1]").split(","))

    @app.middleware("http")
    async def boundary(request, call_next):
        if request.url.path.startswith("/api/"):
            authorization = request.headers.get("authorization", "")
            if not hmac.compare_digest(authorization.encode(), ("Bearer " + token).encode()) and request.method != "OPTIONS":
                return JSONResponse({"detail": "Valid bearer token required"}, status_code=401)
            origin = request.headers.get("origin")
            if origin and origin not in origins:
                return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > 1024 * 1024:
                    return JSONResponse({"detail": "Request exceeds 1 MiB"}, status_code=413)
            request._body = bytes(body)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, error):
        # Pydantic's default response can echo submitted secrets in `input`.
        return JSONResponse({"detail": [{"loc": e["loc"], "type": e["type"]} for e in error.errors()]}, status_code=422)

    @app.exception_handler(Exception)
    async def failed(request, error):
        return JSONResponse({"detail": "Operation failed; analysis incomplete. No GREEN verdict issued."}, status_code=500)

    for kind in (GitError, APIError, ValueError, OSError, sqlite3.Error, subprocess.TimeoutExpired):
        async def known_error(request, error):
            status = 502 if isinstance(error, APIError) else 409 if isinstance(error, GitError) else 400
            message = str(error) if isinstance(error, (GitError, APIError, ValueError)) else "Operation unavailable"
            return JSONResponse({"detail": safe(message), "analysis_complete": False}, status_code=status)
        app.add_exception_handler(kind, known_error)

    def within(path):
        resolved = Path(path).expanduser().resolve()
        if not any(resolved.is_relative_to(root) for root in roots):
            raise HTTPException(403, "Repository path is outside configured roots")
        return resolved

    def validate_repo(path):
        path = within(path)
        repo = Repo(path)
        if repo.root != path: raise HTTPException(400, "Supply the repository root, not a subdirectory")
        within(repo.gitdir)
        common = Path(repo.run("rev-parse", "--git-common-dir").strip())
        within(common if common.is_absolute() else repo.root / common)
        if (repo.gitdir / "precedent.sqlite3").is_symlink():
            raise HTTPException(403, "Evidence database must not be a symlink")
        return repo

    def lookup(repo_id):
        row = state.repository(repo_id)
        if row is None: raise HTTPException(404, "Repository not found")
        return validate_repo(row["path"])

    @contextmanager
    def opened(repo_id):
        repo = lookup(repo_id)
        lock = state.lock(repo.root)
        if not lock.acquire(blocking=False): raise HTTPException(409, "Repository busy; poll its job and retry")
        store = None
        try:
            store = Store(repo)
            yield repo, store
        finally:
            try:
                if store: store.close()
            finally:
                lock.release()

    def relative_path(path):
        p = PurePosixPath(path.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or ".git" in p.parts or ":" in path or not p.parts:
            raise HTTPException(400, "Use a repository-relative file path")
        return p.as_posix()

    def revision(repo, ref):
        return repo.run("rev-parse", "--verify", "--end-of-options", ref + "^{commit}").strip()

    @app.get("/health")
    def health(): return {"status": "ok", "version": __version__}

    protected = [Depends(authenticate)]

    @app.get("/api/v1/repositories", dependencies=protected)
    def repositories(): return clean({"repositories": state.repositories()})

    @app.post("/api/v1/repositories", dependencies=protected, status_code=201)
    def register(body: Register):
        return clean(state.register(validate_repo(body.path).root))

    @app.get("/api/v1/repositories/{repo_id}/status", dependencies=protected)
    def status(repo_id: str):
        with opened(repo_id) as (repo, store):
            return clean(dict(id=repo_id, head=repo.head(), github_repository=store.get("repository"),
                ingestion=store.get("ingestion_status", "not started"), last_ingested=store.get("last_ingested"),
                covered_commits=store.db.execute("SELECT count(*) FROM coverage").fetchone()[0],
                synthetic=store.get("synthetic") == "1", ai_enabled=ai_settings()["enabled"],
                model=ai_settings()["model"], ai=ai_settings()))

    @app.get("/api/v1/repositories/{repo_id}/changes", dependencies=protected)
    def changes(repo_id: str):
        with opened(repo_id) as (repo, store):
            return clean({"scope": "staged", "files": [dict(path=c.path, added_lines=len(c.added), removed_lines=len(c.removed), binary=c.binary) for c in repo.changes()]})

    @app.post("/api/v1/repositories/{repo_id}/stage", dependencies=protected)
    def stage(repo_id: str, body: Stage):
        with opened(repo_id) as (repo, store):
            paths = [relative_path(p) for p in body.paths]
            for path in paths:
                if not (repo.root / path).resolve().is_relative_to(repo.root): raise HTTPException(403, "Path escapes repository")
            repo.run("add", "--", *[":(literal)" + p for p in paths])
            return clean({"staged": paths})

    @app.post("/api/v1/repositories/{repo_id}/check", dependencies=protected)
    def run_check(repo_id: str, body: Check):
        with opened(repo_id) as (repo, store):
            if body.scope == "staged":
                changes = repo.changes()
            else:
                tip = revision(repo, body.tip)
                base = revision(repo, body.base) if body.base else "0" * len(tip)
                args = [tip] + (["^" + base] if body.base else [])
                count = int(repo.run("rev-list", "--count", *args, "--").strip())
                if count > 500: raise HTTPException(413, "Commit range exceeds 500 commits; choose a closer base. Analysis not run.")
                changes = repo.outgoing(f"refs/heads/local {tip} refs/heads/remote {base}\n", "origin")
            report = check(repo, store, changes)
            report["scope"] = body.scope
            report["push_allowed"] = report["verdict"] != "RED"
            return clean(report)

    @app.post("/api/v1/repositories/{repo_id}/why", dependencies=protected)
    def why(repo_id: str, body: Why):
        with opened(repo_id) as (repo, store):
            info = repo.blame(relative_path(body.path), body.line, revision(repo, body.ref))
            evidence = store.evidence(info["sha"])
            output = explain_result(evidence, store, info)
            return clean(dict(**info, evidence=evidence, explanation=output["text"],
                mode=output["mode"], ai=output["ai"], synthetic=store.get("synthetic") == "1",
                note="Blame identifies the last modifying commit, not necessarily original intent."))

    @app.post("/api/v1/repositories/{repo_id}/commit-message", dependencies=protected)
    def message(repo_id: str):
        with opened(repo_id) as (repo, store):
            return clean({**commit_message_result(repo, store), "synthetic": store.get("synthetic") == "1"})

    @app.post("/api/v1/repositories/{repo_id}/secrets", dependencies=protected)
    def secrets_only(repo_id: str):
        with opened(repo_id) as (repo, store): return clean({"findings": scan_secrets(repo.changes()), "scope": "staged"})

    @app.post("/api/v1/repositories/{repo_id}/forecast", dependencies=protected)
    def forecast_only(repo_id: str):
        with opened(repo_id) as (repo, store):
            changes = repo.changes()
            findings = forecast(store, changes)
            return clean({"findings": findings, "ai": review_changes(store, changes, findings, "review_forecast"), "synthetic": store.get("synthetic") == "1",
                          "history_available": bool(store.get("last_ingested")), "scope": "staged"})

    @app.post("/api/v1/repositories/{repo_id}/hooks", dependencies=protected)
    def hooks(repo_id: str, body: Hooks):
        with opened(repo_id) as (repo, store):
            directory = hook_dir(repo).resolve()
            if not directory.is_relative_to(repo.gitdir):
                raise HTTPException(403, "Web installation requires hooks inside this repository's Git directory. Use CLI for shared custom hooks.")
            for name in ("pre-push", "prepare-commit-msg"):
                if (directory / (name + ".precedent-original")).is_symlink():
                    raise HTTPException(403, "Hook backup must not be a symlink")
            install(repo, body.chain_existing)
            return {"installed": ["pre-push", "prepare-commit-msg"], "location": "backend host", "repo_id": repo_id}

    @app.post("/api/v1/repositories/{repo_id}/ingest", dependencies=protected, status_code=202)
    def start_ingestion(repo_id: str, body: Ingest):
        repo = lookup(repo_id)
        lock = state.lock(repo.root)
        if not lock.acquire(blocking=False): raise HTTPException(409, "Repository busy")
        try:
            job_id = state.new_job(repo_id)
            def task():
                store = None
                try:
                    state.update_job(job_id, "running", "Fetching GitHub evidence")
                    repo = lookup(repo_id)
                    store = Store(repo)
                    count = ingest(repo, store, body.repository, body.limit, body.refresh,
                        progress=lambda text: state.update_job(job_id, "running", safe(text)))
                    state.update_job(job_id, "succeeded", "Complete", result={"selected_commits": count})
                except Exception as exc:
                    error = safe(str(exc)) if isinstance(exc, (GitError, APIError, ValueError)) else "Ingestion failed; cached coverage may be incomplete."
                    state.update_job(job_id, "failed", error=error)
                finally:
                    try:
                        if store: store.close()
                    finally: lock.release()
            state.pool.submit(task)
        except Exception:
            lock.release()
            raise
        return {"job_id": job_id, "status_url": f"/api/v1/jobs/{job_id}"}

    @app.get("/api/v1/jobs/{job_id}", dependencies=protected)
    def job(job_id: str):
        value = state.job(job_id)
        if value is None: raise HTTPException(404, "Job not found")
        return clean(value)

    # Outermost CORS also decorates authentication/validation error responses.
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["Authorization", "Content-Type"], allow_credentials=False)
    return app


def main():
    import uvicorn
    uvicorn.run("precedent.web.server:create_app", factory=True,
                host=os.environ.get("PRECEDENT_BIND", "127.0.0.1"),
                port=int(os.environ.get("PRECEDENT_PORT", "8000")), workers=1)


if __name__ == "__main__": main()
