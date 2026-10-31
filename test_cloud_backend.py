"""Unit tests plus real PostgreSQL integration tests (NEXUS_TEST_DATABASE_URL)."""
from contextlib import contextmanager
from pathlib import Path
import os
import subprocess
from urllib.parse import parse_qs, urlsplit
import uuid

import pytest
pytest.importorskip('psycopg')
from cryptography.fernet import Fernet
from fastapi import HTTPException
from fastapi.testclient import TestClient
import psycopg
from psycopg import sql

from precedent.cloud.config import Config
from precedent.cloud.db import Database, digest
from precedent.cloud.github import GitHub
from precedent.cloud.repository import CloudRepo
from precedent.cloud.server import create_app, SESSION, STATE


@pytest.fixture
def config():
    return Config('postgresql://unused/test', 'https://nexus-test.vercel.app',
                  'https://api.example.test', 'test-client', 'test-secret', Fernet.generate_key().decode())


@pytest.mark.parametrize('value', ['*', 'https://*.vercel.app', 'http://localhost:5173',
    'https://site.vercel.app/', 'https://site.vercel.app/path', 'https://user:pass@site.vercel.app',
    'https://site.vercel.app?x=1'])
def test_exact_origin_only(config, value):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(config, frontend_origin=value)


def test_cloud_rejects_sqlite(config):
    from dataclasses import replace
    with pytest.raises(ValueError):
        replace(config, database_url='sqlite:///local.db')


def test_boundary_without_database(config):
    app = create_app(config)
    with TestClient(app, base_url=config.frontend_origin) as c:
        assert c.get('/api/cloud/repositories').status_code == 401
        assert c.get('/api/v1/repositories', headers={'Authorization': 'Bearer old-shared-token'}).status_code == 404
        assert c.post('/api/cloud/repositories', headers={'Origin': 'https://evil.test'}).status_code == 403
        assert c.post('/api/cloud/repositories').status_code == 403
        preflight = c.options('/api/cloud/repositories', headers={'Origin': config.frontend_origin,
            'Access-Control-Request-Method': 'POST', 'Access-Control-Request-Headers': 'X-CSRF-Token'})
        assert preflight.headers['access-control-allow-origin'] == config.frontend_origin
        assert preflight.headers['access-control-allow-credentials'] == 'true'
        assert c.get('/health', headers={'Host': 'evil.test'}).status_code == 400
        response = c.post('/api/cloud/repositories', content='x'*16385, headers={'Origin': config.frontend_origin})
        assert response.status_code == 413


def test_membership_required_even_for_public_repository(monkeypatch):
    gh = GitHub('test-token')
    monkeypatch.setattr(gh, 'get', lambda path: {'id': 1, 'private': False})
    with pytest.raises(HTTPException) as error:
        gh.repository(1)
    assert error.value.status_code == 404


def test_revision_rejects_option_injection(tmp_path):
    repo = CloudRepo(tmp_path, {})
    for value in ['--upload-pack=evil', '../private', 'HEAD;evil', 'HEAD^{tree}']:
        with pytest.raises(HTTPException):
            repo.revision(value)


@pytest.fixture
def database():
    url = os.environ.get('NEXUS_TEST_DATABASE_URL')
    if not url:
        pytest.skip('Set NEXUS_TEST_DATABASE_URL to run real PostgreSQL integration tests')
    # Isolated schema, never truncate another database's tables.
    schema = 'test_' + uuid.uuid4().hex
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('CREATE SCHEMA {}').format(sql.Identifier(schema)))
    class SchemaDatabase(Database):
        @contextmanager
        def connect(self):
            with super().connect() as conn:
                conn.execute(sql.SQL('SET search_path TO {}').format(sql.Identifier(schema)))
                yield conn
    db = SchemaDatabase(url)
    with db.connect() as conn:
        conn.execute(Path('migrations/001_cloud.sql').read_text())
    yield db
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(sql.SQL('DROP SCHEMA {} CASCADE').format(sql.Identifier(schema)))


class FakeGitHub:
    revoked = False
    def __init__(self, token):
        self.token = token
    def get(self, path, params=None):
        if path == '/user':
            return {'id': 1, 'login': 'alice'}
        if path == '/user/repos':
            return [self.repository(10)]
        if '/commits/' in path:
            return {'commit': {'message': 'test history'}}
        raise AssertionError(path)
    def pages(self, path):
        return iter([])
    def repository(self, identifier):
        if self.revoked or identifier != 10:
            raise HTTPException(404, 'Access denied')
        return {'id': 10, 'full_name': 'alice/demo', 'private': True,
                'default_branch': 'main', 'size': 1, 'permissions': {'pull': True}}


@pytest.fixture
def setup(config, database, monkeypatch, tmp_path):
    monkeypatch.setenv('PRECEDENT_AI', '0')
    FakeGitHub.revoked = False
    repo_path = tmp_path / 'repo'
    repo_path.mkdir()
    def git(*args):
        return subprocess.check_output(['git', *args], cwd=repo_path, text=True).strip()
    git('init', '-b', 'main')
    git('config', 'user.email', 'test@example.test')
    git('config', 'user.name', 'Test')
    (repo_path / 'a.py').write_text('def parse(x):\n    if not x: return None\n    return x[0]\n')
    git('add', '.')
    git('commit', '-m', 'fix: guard input')
    git('branch', 'baseline')
    (repo_path / 'a.py').write_text('def parse(x):\n    return x[0]\n')
    git('add', '.')
    git('commit', '-m', 'refactor: simplify')
    @contextmanager
    def local_clone(metadata, token):
        # Independent copy to test persistence across otherwise stateless operations.
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            subprocess.run(['git', 'clone', '--bare', str(repo_path), root], check=True, capture_output=True)
            yield CloudRepo(root, {'PATH': os.environ['PATH'], 'HOME': root, 'GIT_CONFIG_NOSYSTEM': '1'})
    cipher = Fernet(config.encryption_key.encode())
    with database.connect() as conn:
        for i, name in [(1, 'alice'), (2, 'bob')]:
            conn.execute('INSERT INTO nexus_users VALUES (%s,%s,%s)', (i, name, cipher.encrypt(b'test-github-token')))
            conn.execute("INSERT INTO nexus_sessions VALUES (%s,%s,%s,now()+interval '1 hour')", (digest(name), i, name+'-csrf'))
    def client(name='alice'):
        c = TestClient(create_app(config, database, FakeGitHub, local_clone), base_url=config.frontend_origin)
        c.cookies.set(SESSION, name)
        c.headers.update({'Origin': config.frontend_origin, 'X-CSRF-Token': name+'-csrf'})
        return c
    return client, database


def test_tenant_isolation_and_csrf(setup):
    factory, db = setup
    alice, bob = factory(), factory('bob')
    row = alice.post('/api/cloud/repositories', json={'github_id': 10}).json()
    repo = '/api/cloud/repositories/' + row['id']
    assert bob.get('/api/cloud/repositories').json() == {'repositories': []}
    assert bob.get(repo+'/history').status_code == 404
    assert bob.get(repo+'/status').status_code == 404
    assert bob.post(repo+'/check', json={'base': 'baseline', 'tip': 'main'}).status_code == 404
    assert bob.post(repo+'/hooks').status_code == 404
    assert alice.post(repo+'/hooks').status_code == 409
    assert alice.post('/api/cloud/repositories', json={'path': '/etc'}).status_code == 422
    assert alice.post('/api/cloud/repositories', json={'github_id': 10}, headers={'X-CSRF-Token': 'bad'}).status_code == 403
    assert alice.post('/api/cloud/repositories', json={'github_id': 99}).status_code == 404
    FakeGitHub.revoked = True
    assert alice.get(repo+'/history').status_code == 404
    assert alice.post(repo+'/check', json={'base': 'baseline', 'tip': 'main'}).status_code == 404


def test_analysis_persists_across_app_instances(setup):
    factory, db = setup
    c = factory()
    row = c.post('/api/cloud/repositories', json={'github_id': 10}).json()
    path = '/api/cloud/repositories/' + row['id']
    ingested = c.post(path+'/ingest', json={'limit': 5})
    assert ingested.status_code == 200, ingested.text
    assert ingested.json()['selected_commits'] == 2
    for action in ['check', 'secrets', 'forecast', 'commit-message']:
        response = c.post(path+'/'+action, json={'base': 'baseline', 'tip': 'main'})
        assert response.status_code == 200, response.text
        assert 'report_id' in response.json()
        assert 'test-github-token' not in response.text
    why = c.post(path+'/why', json={'path': 'a.py', 'line': 1, 'ref': 'main'})
    assert why.status_code == 200
    assert factory().get(path+'/history').status_code == 200
    assert len(factory().get(path+'/history').json()['reports']) == 5
    with db.connect() as conn:
        evidence = bytes(conn.execute('SELECT evidence FROM nexus_repositories WHERE id=%s', (row['id'],)).fetchone()['evidence'])
        assert evidence and not evidence.startswith(b'SQLite')
    assert c.post('/api/cloud/auth/logout').status_code == 200
    assert factory().get('/api/cloud/auth/me').status_code == 401


def test_expired_session_rate_limit_and_delete(setup):
    factory, db = setup
    with db.connect() as conn:
        conn.execute("UPDATE nexus_sessions SET expires=now()-interval '1 minute' WHERE user_id=2")
    assert factory('bob').get('/api/cloud/auth/me').status_code == 401
    db.limit('test', 1)
    with pytest.raises(HTTPException) as error:
        db.limit('test', 1)
    assert error.value.status_code == 429
    assert factory().delete('/api/cloud/account').status_code == 200
    assert factory().get('/api/cloud/auth/me').status_code == 401


def test_oauth_pkce_state_replay_and_cookie_flags(config, database, monkeypatch):
    import httpx
    seen = {}
    def exchange(url, **kwargs):
        seen.update(kwargs['data'])
        return httpx.Response(200, json={'access_token': 'fake-token', 'scope': 'read:user,repo'},
                              request=httpx.Request('POST', url))
    monkeypatch.setattr('precedent.cloud.server.httpx.post', exchange)
    c = TestClient(create_app(config, database, FakeGitHub), base_url=config.frontend_origin, follow_redirects=False)
    start = c.get('/api/cloud/auth/login')
    query = parse_qs(urlsplit(start.headers['location']).query)
    assert query['code_challenge_method'] == ['S256']
    assert 'HttpOnly' in start.headers['set-cookie'] and 'Secure' in start.headers['set-cookie']
    state = query['state'][0]
    assert c.get('/api/cloud/auth/callback', params={'code': 'test-code', 'state': 'wrong'}).status_code == 400
    good = c.get('/api/cloud/auth/callback', params={'code': 'test-code', 'state': state})
    assert good.status_code == 303
    assert good.headers['location'] == config.frontend_origin + '/'
    assert 'code_verifier' in seen and seen['client_secret'] == config.client_secret
    assert 'fake-token' not in good.text and 'fake-token' not in str(good.headers)
    assert c.get('/api/cloud/auth/me').json()['login'] == 'alice'
    c.cookies.set(STATE, state)
    assert c.get('/api/cloud/auth/callback', params={'code': 'test-code', 'state': state}).status_code == 400
