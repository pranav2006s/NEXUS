"""Disposable bare clones. No checkout, filters, hooks, submodules or code execution."""
from contextlib import contextmanager
from pathlib import Path
import base64
import os
import re
import subprocess
import tempfile
from fastapi import HTTPException
from ..gitops import Repo, GitError


class CloudRepo(Repo):
    def __init__(self, path, env):
        self.root = self.gitdir = Path(path)
        self.env = env
        self.selected = None

    def run(self, *args, input=None, check=True):
        # File-backed output bounds memory, including malicious large Git blobs.
        with tempfile.TemporaryFile() as out:
            p = subprocess.run(['git', '-c', 'core.quotePath=false', '-c', 'core.hooksPath=/dev/null',
                                *args], cwd=self.root, env=self.env, input=input,
                               text=True, stdout=out, stderr=subprocess.DEVNULL, timeout=60)
            if out.tell() > 8 * 1024 * 1024:
                raise HTTPException(413, 'Git output too large; analysis incomplete')
            if p.returncode and check:
                raise GitError('Git operation failed; verify repository and revisions')
            out.seek(0)
            return out.read().decode('utf-8', errors='replace')

    def changes(self, base=None, tip=None):
        if base is None and tip is None:
            return self.selected or []
        return super().changes(base, tip)

    def revision(self, value):
        if not re.fullmatch(r'[A-Za-z0-9_./-]{1,200}', value) or value.startswith('-') or '..' in value:
            raise HTTPException(422, 'Use a branch name or commit SHA')
        return self.run('rev-parse', '--verify', '--end-of-options', value + '^{commit}').strip()


@contextmanager
def clone(metadata, token):
    name = metadata['full_name']
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name):
        raise GitError('Invalid repository name')
    if metadata.get('size', 0) > 100_000:
        raise HTTPException(413, 'Repository exceeds hosted 100 MB metadata limit')
    with tempfile.TemporaryDirectory(prefix='nexus-') as directory:
        root = Path(directory)
        env = {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'HOME': directory,
               'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
               'GIT_TERMINAL_PROMPT': '0', 'GIT_ALLOW_PROTOCOL': 'https'}
        repo = CloudRepo(root, env)
        repo.run('init', '--bare', '.')
        repo.run('remote', 'add', 'origin', f'https://github.com/{name}.git')
        # Environment, not argv or Git config on disk; remove after fetch.
        auth = base64.b64encode(('x-access-token:' + token).encode()).decode()
        env.update(GIT_CONFIG_COUNT='1', GIT_CONFIG_KEY_0='http.https://github.com/.extraheader',
                   GIT_CONFIG_VALUE_0='Authorization: Basic ' + auth)
        try:
            repo.run('fetch', '--no-tags', '--no-recurse-submodules', 'origin', '+refs/heads/*:refs/heads/*')
        finally:
            for key in ('GIT_CONFIG_COUNT', 'GIT_CONFIG_KEY_0', 'GIT_CONFIG_VALUE_0'):
                env.pop(key, None)
        branch = metadata['default_branch']
        repo.run('symbolic-ref', 'HEAD', 'refs/heads/' + branch)
        yield repo
