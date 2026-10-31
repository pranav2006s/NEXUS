"""Only GitHub fixed-host requests; never accept an arbitrary remote URL."""
import httpx
from fastapi import HTTPException
from ..ingestion import APIError


class GitHub:
    def __init__(self, token):
        self.token = token
        self.requests = 0

    def get(self, path, params=None):
        if not path.startswith(('/user', '/repositories/', '/repos/')) or '..' in path:
            raise APIError('Invalid GitHub path')
        self.requests += 1
        if self.requests > 250:
            raise APIError('GitHub request budget exceeded; reduce ingestion limit')
        try:
            with httpx.Client(timeout=20, follow_redirects=False) as client:
                with client.stream('GET', 'https://api.github.com' + path, params=params,
                    headers={'Authorization': 'Bearer ' + self.token,
                             'Accept': 'application/vnd.github+json',
                             'X-GitHub-Api-Version': '2022-11-28'}) as response:
                    if response.status_code == 401:
                        raise HTTPException(401, 'GitHub authorization expired; sign in again')
                    if response.status_code in (403, 404):
                        raise HTTPException(404, 'Repository unavailable or access denied')
                    if response.status_code != 200:
                        raise APIError('GitHub unavailable; retry later')
                    content = bytearray()
                    for chunk in response.iter_bytes():
                        content.extend(chunk)
                        if len(content) > 4 * 1024 * 1024:
                            raise APIError('GitHub response exceeds safety limit')
                    import json
                    return json.loads(content)
        except (httpx.HTTPError, ValueError):
            raise APIError('GitHub unavailable; analysis incomplete') from None

    def pages(self, path):
        for page in range(1, 11):
            sep = '&' if '?' in path else '?'
            data = self.get(f'{path}{sep}per_page=100&page={page}')
            if not isinstance(data, list):
                raise APIError('Invalid GitHub collection')
            yield from data
            if len(data) < 100:
                return
        raise APIError('Pagination limit exceeded; coverage incomplete')

    def repository(self, github_id):
        data = self.get(f'/repositories/{github_id}')
        # Public repositories can be read anonymously: require actual membership.
        if data.get('id') != github_id or not data.get('permissions', {}).get('pull'):
            raise HTTPException(404, 'Repository unavailable or access denied')
        return data
