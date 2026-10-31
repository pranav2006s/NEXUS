"""Cloud entry point. Never mounts the shared-token/local-filesystem API."""
import base64
from contextlib import contextmanager
from datetime import datetime
import hmac
import json
from pathlib import PurePosixPath
import secrets
import uuid
from urllib.parse import urlencode, urlsplit

from cryptography.fernet import Fernet
import httpx
from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, ConfigDict, Field
from psycopg.types.json import Jsonb
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..ai import commit_message_result, explain_result, review_changes
from ..analysis import check, forecast, secrets as scan_secrets
from ..cloud_ai import settings as ai_settings
from ..ingestion import ingest, APIError
from ..gitops import GitError
from ..storage import Store
from ..web.server import clean
from .config import Config
from .db import Database, digest
from .github import GitHub
from .repository import clone

SESSION = '__Host-nexus-session'
STATE = '__Host-nexus-oauth'


class Body(BaseModel):
    model_config = ConfigDict(extra='forbid')


class Selection(Body):
    github_id: int = Field(gt=0)


class Comparison(Body):
    base: str = Field(min_length=1, max_length=200)
    tip: str = Field(min_length=1, max_length=200)


class Ingestion(Body):
    limit: int = Field(default=20, ge=1, le=50)
    refresh: bool = False


class Line(Body):
    path: str = Field(min_length=1, max_length=1024)
    line: int = Field(ge=1, le=1000000)
    ref: str = Field(default='HEAD', min_length=1, max_length=200)


def cookie(response, name, value, age):
    response.set_cookie(name, value, max_age=age, secure=True, httponly=True, samesite='lax', path='/')


def create_app(config=None, database=None, github_factory=GitHub, clone_factory=clone):
    config = config or Config.from_env()
    db = database or Database(config.database_url)
    cipher = Fernet(config.encryption_key.encode())
    app = FastAPI(title='NEXUS Cloud API', docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list({urlsplit(config.api_origin).hostname,
                                                               urlsplit(config.frontend_origin).hostname}))

    @app.middleware('http')
    async def boundary(request, call_next):
        origin = request.headers.get('origin')
        if origin and origin != config.frontend_origin:
            return JSONResponse({'detail': 'Origin not allowed'}, status_code=403)
        if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin != config.frontend_origin:
            return JSONResponse({'detail': 'Exact frontend Origin required'}, status_code=403)
        data = bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data) > 16384:
                return JSONResponse({'detail': 'Request too large'}, status_code=413)
        request._body = bytes(data)
        response = await call_next(request)
        response.headers.update({'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                                 'Referrer-Policy': 'no-referrer'})
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid(request, exc):
        return JSONResponse({'detail': 'Invalid request fields'}, status_code=422)

    @app.exception_handler(Exception)
    async def failed(request, exc):
        return JSONResponse({'detail': 'Operation failed; analysis incomplete'}, status_code=500)

    async def external_error(request, exc):
        return JSONResponse({'detail': 'Repository/provider operation failed; analysis incomplete'}, status_code=502)
    app.add_exception_handler(APIError, external_error)
    app.add_exception_handler(GitError, external_error)

    def identity(request: Request):
        token = request.cookies.get(SESSION, '')
        if not token or len(token) > 128:
            raise HTTPException(401, 'Sign in required')
        with db.connect() as conn:
            row = conn.execute('''SELECT s.user_id, s.csrf, u.login, u.token FROM nexus_sessions s
                JOIN nexus_users u ON u.id=s.user_id WHERE s.hash=%s AND s.expires>now()''', (digest(token),)).fetchone()
        if not row:
            raise HTTPException(401, 'Session expired; sign in again')
        if request.method not in ('GET', 'HEAD', 'OPTIONS'):
            if not hmac.compare_digest(request.headers.get('x-csrf-token', '').encode(), row['csrf'].encode()):
                raise HTTPException(403, 'CSRF token required')
        return row

    def client(user):
        return github_factory(cipher.decrypt(bytes(user['token'])).decode())

    def owned(conn, repo_id, user):
        row = conn.execute('SELECT * FROM nexus_repositories WHERE id=%s AND user_id=%s',
                           (repo_id, user['user_id'])).fetchone()
        if not row:
            raise HTTPException(404, 'Repository not found')
        return row

    @contextmanager
    def operation(repo_id, user):
        db.limit('analysis:' + str(user['user_id']), 30)
        with db.connect() as conn:
            row = owned(conn, repo_id, user)
            # Transaction advisory lock works across processes/replicas; no shared clone.
            lock_id = int(digest(repo_id)[:15], 16)
            if not conn.execute('SELECT pg_try_advisory_xact_lock(%s) AS locked', (lock_id,)).fetchone()['locked']:
                raise HTTPException(409, 'Repository busy; retry later')
            gh = client(user)
            metadata = gh.repository(row['github_id'])  # re-check revoked membership every time
            with clone_factory(metadata, gh.token) as repo:
                path = repo.gitdir / 'precedent.sqlite3'
                if row['evidence']:
                    path.write_bytes(cipher.decrypt(bytes(row['evidence'])))
                store = Store(repo)
                try:
                    yield conn, repo, store, gh, metadata
                    store.db.commit()
                    snapshot = store.db.serialize()
                    if len(snapshot) > 32 * 1024 * 1024:
                        raise HTTPException(413, 'Evidence store limit reached')
                    conn.execute('UPDATE nexus_repositories SET evidence=%s,full_name=%s WHERE id=%s AND user_id=%s',
                        (cipher.encrypt(snapshot), metadata['full_name'], repo_id, user['user_id']))
                finally:
                    store.close()

    def save(conn, repo_id, user, action, result):
        result = clean(result)
        report_id = str(uuid.uuid4())
        conn.execute('INSERT INTO nexus_reports(id,repository_id,user_id,action,result) VALUES (%s,%s,%s,%s,%s)',
                     (report_id, repo_id, user['user_id'], action, Jsonb(result)))
        return {**result, 'report_id': report_id}

    def compare(repo, body, every_commit=False):
        base, tip = repo.revision(body.base), repo.revision(body.tip)
        count = int(repo.run('rev-list', '--count', tip, '^' + base, '--').strip())
        if count > 100:
            raise HTTPException(413, 'Comparison exceeds 100 commits; select a closer base')
        if every_commit:
            changes = repo.outgoing(f'refs/heads/local {tip} refs/heads/base {base}\n', 'origin')
        else:
            changes = repo.changes(base, tip)
        if len(changes) > 500 or sum(len(c.added) + len(c.removed) for c in changes) > 20000:
            raise HTTPException(413, 'Comparison too large; analysis incomplete')
        repo.selected = changes
        return changes, {'base': base, 'tip': tip, 'scope': 'commits' if every_commit else 'comparison'}

    @app.get('/health')
    def health():
        with db.connect() as conn:
            conn.execute('SELECT 1 FROM nexus_users LIMIT 1')
        return {'status': 'ok', 'mode': 'cloud'}

    @app.get('/api/cloud/auth/login')
    def login():
        # No redirect target accepted from browser. State is browser-bound and one-use.
        db.limit('oauth:global', 300, 60)
        state, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
        with db.connect() as conn:
            conn.execute('DELETE FROM nexus_oauth WHERE expires<now()')
            conn.execute("INSERT INTO nexus_oauth VALUES (%s,%s,now()+interval '10 minutes')",
                         (digest(state), cipher.encrypt(verifier.encode())))
        challenge = base64.urlsafe_b64encode(bytes.fromhex(digest(verifier))).rstrip(b'=').decode()
        response = RedirectResponse('https://github.com/login/oauth/authorize?' + urlencode({
            'client_id': config.client_id, 'redirect_uri': config.callback, 'scope': 'read:user repo',
            'state': state, 'code_challenge': challenge, 'code_challenge_method': 'S256'}), status_code=302)
        cookie(response, STATE, state, 600)
        return response

    @app.get('/api/cloud/auth/callback')
    def callback(request: Request, code: str = Query(max_length=512), state: str = Query(max_length=128)):
        if not hmac.compare_digest(state.encode(), request.cookies.get(STATE, '').encode()):
            raise HTTPException(400, 'Invalid OAuth state')
        with db.connect() as conn:
            attempt = conn.execute('DELETE FROM nexus_oauth WHERE hash=%s AND expires>now() RETURNING verifier',
                                   (digest(state),)).fetchone()
        if not attempt:
            raise HTTPException(400, 'OAuth state expired or already used')
        try:
            response = httpx.post('https://github.com/login/oauth/access_token', timeout=20,
                headers={'Accept': 'application/json'}, data={'client_id': config.client_id,
                'client_secret': config.client_secret, 'redirect_uri': config.callback, 'code': code,
                'code_verifier': cipher.decrypt(bytes(attempt['verifier'])).decode()})
            response.raise_for_status()
            payload = response.json()
            token = payload['access_token']
            if not isinstance(token, str) or not {'repo', 'read:user'} <= set(payload.get('scope', '').split(',')):
                raise ValueError('Required scope missing')
            github_user = github_factory(token).get('/user')
        except (httpx.HTTPError, KeyError, ValueError):
            raise HTTPException(401, 'GitHub sign-in failed') from None
        session, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
        with db.connect() as conn:
            conn.execute('''INSERT INTO nexus_users VALUES (%s,%s,%s) ON CONFLICT(id)
                DO UPDATE SET login=EXCLUDED.login,token=EXCLUDED.token''',
                (github_user['id'], github_user['login'], cipher.encrypt(token.encode())))
            # Rotating login invalidates previous sessions for this identity.
            conn.execute('DELETE FROM nexus_sessions WHERE user_id=%s OR expires<now()', (github_user['id'],))
            conn.execute("INSERT INTO nexus_sessions VALUES (%s,%s,%s,now()+interval '8 hours')",
                         (digest(session), github_user['id'], csrf))
        response = RedirectResponse(config.frontend_origin + '/', status_code=303)
        response.delete_cookie(STATE, secure=True, httponly=True, samesite='lax')
        cookie(response, SESSION, session, 8 * 3600)
        return response

    @app.get('/api/cloud/auth/me')
    def me(user=Depends(identity)):
        return {'id': user['user_id'], 'login': user['login'], 'csrf_token': user['csrf']}

    @app.post('/api/cloud/auth/logout')
    def logout(request: Request, user=Depends(identity)):
        with db.connect() as conn:
            conn.execute('DELETE FROM nexus_sessions WHERE hash=%s', (digest(request.cookies[SESSION]),))
        response = JSONResponse({'signed_out': True})
        response.delete_cookie(SESSION, secure=True, httponly=True, samesite='lax')
        return response

    @app.delete('/api/cloud/account')
    def disconnect(user=Depends(identity)):
        with db.connect() as conn:
            conn.execute('DELETE FROM nexus_users WHERE id=%s', (user['user_id'],))
        response = JSONResponse({'deleted': True, 'note': 'Revoke the OAuth app in GitHub Settings to revoke its grant.'})
        response.delete_cookie(SESSION, secure=True, httponly=True, samesite='lax')
        return response

    @app.get('/api/cloud/capabilities')
    def capabilities(user=Depends(identity)):
        return {'mode': 'cloud', 'source': 'GitHub committed revisions',
                'available': ['check', 'secrets', 'forecast', 'why', 'commit-message', 'ingest', 'history'],
                'local_only': ['stage', 'hooks', 'uncommitted changes', 'push interception'], 'ai': ai_settings()}

    @app.get('/api/cloud/github/repositories')
    def available(page: int = Query(default=1, ge=1, le=100), user=Depends(identity)):
        db.limit('github:' + str(user['user_id']), 200)
        repos = client(user).get('/user/repos', {'per_page': 50, 'page': page, 'sort': 'updated',
                                               'affiliation': 'owner,collaborator,organization_member'})
        return {'repositories': [{'github_id': r['id'], 'full_name': r['full_name'],
                'private': r['private'], 'default_branch': r['default_branch']} for r in repos],
                'next_page': page + 1 if len(repos) == 50 else None}

    @app.get('/api/cloud/repositories')
    def repositories(user=Depends(identity)):
        with db.connect() as conn:
            rows = conn.execute('SELECT id,github_id,full_name FROM nexus_repositories WHERE user_id=%s',
                                (user['user_id'],)).fetchall()
        return {'repositories': rows}

    @app.post('/api/cloud/repositories', status_code=201)
    def register(body: Selection, user=Depends(identity)):
        db.limit('github:' + str(user['user_id']), 200)
        metadata = client(user).repository(body.github_id)
        with db.connect() as conn:
            row = conn.execute('''INSERT INTO nexus_repositories(id,user_id,github_id,full_name)
                VALUES (%s,%s,%s,%s) ON CONFLICT(user_id,github_id) DO UPDATE SET full_name=EXCLUDED.full_name
                RETURNING id,github_id,full_name''',
                (str(uuid.uuid4()), user['user_id'], metadata['id'], metadata['full_name'])).fetchone()
        return row

    @app.get('/api/cloud/repositories/{repo_id}/status')
    def status(repo_id: str, user=Depends(identity)):
        with db.connect() as conn:
            row = owned(conn, repo_id, user)
        db.limit('github:' + str(user['user_id']), 200)
        metadata = client(user).repository(row['github_id'])
        return {'id': repo_id, 'full_name': metadata['full_name'], 'default_branch': metadata['default_branch'],
                'evidence_available': bool(row['evidence']), 'ai': ai_settings()}

    @app.post('/api/cloud/repositories/{repo_id}/ingest')
    def ingestion(repo_id: str, body: Ingestion, user=Depends(identity)):
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            count = ingest(repo, store, metadata['full_name'], body.limit, body.refresh,
                           progress=lambda _: None, client=gh)
            return {'selected_commits': count, 'status': 'complete_bounded_sample'}

    @app.post('/api/cloud/repositories/{repo_id}/check')
    def checking(repo_id: str, body: Comparison, user=Depends(identity)):
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            changes, refs = compare(repo, body, every_commit=True)
            result = check(repo, store, changes)
            return save(conn, repo_id, user, 'check', {**result, **refs,
                'advisory_only': True, 'push_intercepted': False})

    @app.post('/api/cloud/repositories/{repo_id}/secrets')
    def scanning(repo_id: str, body: Comparison, user=Depends(identity)):
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            changes, refs = compare(repo, body, every_commit=True)
            return save(conn, repo_id, user, 'secrets', {'findings': scan_secrets(changes), **refs})

    @app.post('/api/cloud/repositories/{repo_id}/forecast')
    def forecasting(repo_id: str, body: Comparison, user=Depends(identity)):
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            changes, refs = compare(repo, body)
            findings = forecast(store, changes)
            return save(conn, repo_id, user, 'forecast', {'findings': findings, **refs,
                'history_available': bool(store.get('last_ingested')),
                'ai': review_changes(store, changes, findings, 'review_forecast')})

    @app.post('/api/cloud/repositories/{repo_id}/commit-message')
    def message(repo_id: str, body: Comparison, user=Depends(identity)):
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            _, refs = compare(repo, body)
            return save(conn, repo_id, user, 'commit-message', {**commit_message_result(repo, store), **refs})

    @app.post('/api/cloud/repositories/{repo_id}/why')
    def why(repo_id: str, body: Line, user=Depends(identity)):
        path = PurePosixPath(body.path)
        if path.is_absolute() or '..' in path.parts or '.git' in path.parts or '\\' in body.path or ':' in body.path:
            raise HTTPException(422, 'Use a repository-relative path')
        with operation(repo_id, user) as (conn, repo, store, gh, metadata):
            info = repo.blame(body.path, body.line, repo.revision(body.ref))
            evidence = store.evidence(info['sha'])
            output = explain_result(evidence, store, info)
            return save(conn, repo_id, user, 'why', {**info, 'evidence': evidence,
                'explanation': output['text'], 'mode': output['mode'], 'ai': output['ai']})

    @app.get('/api/cloud/repositories/{repo_id}/history')
    def history(repo_id: str, before: datetime | None = None, user=Depends(identity)):
        db.limit('github:' + str(user['user_id']), 200)
        with db.connect() as conn:
            row = owned(conn, repo_id, user)
            client(user).repository(row['github_id'])
            rows = conn.execute('''SELECT id,action,result,created FROM nexus_reports
                WHERE repository_id=%s AND user_id=%s AND (%s::timestamptz IS NULL OR created<%s::timestamptz)
                ORDER BY created DESC LIMIT 50''', (repo_id, user['user_id'], before, before)).fetchall()
        return {'reports': rows}

    @app.post('/api/cloud/repositories/{repo_id}/hooks')
    @app.post('/api/cloud/repositories/{repo_id}/stage')
    def local_only(repo_id: str, user=Depends(identity)):
        with db.connect() as conn:
            owned(conn, repo_id, user)
        raise HTTPException(409, 'Local companion required; hosted service cannot access your Git index or install laptop hooks')

    app.add_middleware(CORSMiddleware, allow_origins=[config.frontend_origin], allow_credentials=True,
                       allow_methods=['GET', 'POST', 'DELETE'], allow_headers=['Content-Type', 'X-CSRF-Token'])
    return app
