from dataclasses import dataclass
import os
from urllib.parse import urlsplit
from cryptography.fernet import Fernet


def origin(value):
    p = urlsplit(value)
    if p.scheme != 'https' or not p.hostname or p.username or p.password or p.path or p.query or p.fragment or '*' in value:
        raise ValueError('Use one exact HTTPS origin without a trailing slash')
    return value


@dataclass(frozen=True)
class Config:
    database_url: str
    frontend_origin: str
    api_origin: str
    client_id: str
    client_secret: str
    encryption_key: str

    def __post_init__(self):
        origin(self.frontend_origin)
        origin(self.api_origin)
        if not self.database_url.startswith(('postgresql://', 'postgres://')):
            raise ValueError('Cloud mode requires PostgreSQL')
        if not self.client_id or not self.client_secret:
            raise ValueError('GitHub OAuth configuration required')
        Fernet(self.encryption_key.encode())

    @property
    def callback(self):
        # Same-origin Vercel rewrite avoids third-party session cookies.
        return self.frontend_origin + '/api/cloud/auth/callback'

    @classmethod
    def from_env(cls):
        return cls(*(os.environ[k] for k in ('DATABASE_URL', 'NEXUS_FRONTEND_ORIGIN',
            'NEXUS_API_ORIGIN', 'GITHUB_CLIENT_ID', 'GITHUB_CLIENT_SECRET', 'NEXUS_ENCRYPTION_KEY')))
