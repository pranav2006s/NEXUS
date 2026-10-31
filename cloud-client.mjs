// Same-origin Vercel rewrite; no GitHub/Gemini/shared bearer token in the browser.
export class NexusCloudAPI {
  csrf = null;
  login() { window.location.assign('/api/cloud/auth/login'); }
  async request(path, method = 'GET', body) {
    const response = await fetch('/api/cloud' + path, {
      method, credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...(this.csrf ? { 'X-CSRF-Token': this.csrf } : {}) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.detail || 'Request failed');
    return data;
  }
  async me() { const user = await this.request('/auth/me'); this.csrf = user.csrf_token; return user; }
  available(page = 1) { return this.request(`/github/repositories?page=${page}`); }
  register(github_id) { return this.request('/repositories', 'POST', { github_id }); }
  repositories() { return this.request('/repositories'); }
  analyze(id, action, body) { return this.request(`/repositories/${encodeURIComponent(id)}/${action}`, 'POST', body); }
  history(id) { return this.request(`/repositories/${encodeURIComponent(id)}/history`); }
  async logout() { await this.request('/auth/logout', 'POST'); this.csrf = null; }
}
