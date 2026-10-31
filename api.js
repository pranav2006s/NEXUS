/**
 * NEXUS Backend Client for FastAPI v0.3.1
 * Communicates with the local or trusted-host companion API.
 * Bearer token is kept strictly in memory within the class instance.
 */
export class NexusAPI {
  constructor(baseURL, token) {
    this.baseURL = (baseURL || 'http://127.0.0.1:8000').replace(/\/+$/, '');
    this.token = token || '';
  }

  /**
   * Health check endpoint at root /health (unauthenticated).
   */
  async health() {
    let response;
    try {
      response = await fetch(`${this.baseURL}/health`, {
        method: 'GET',
        cache: 'no-store',
      });
    } catch {
      throw new Error('Cannot reach NEXUS backend health check. Verify backend is running.');
    }
    if (!response.ok) {
      throw new Error(`Health check failed with status ${response.status}`);
    }
    return response.json();
  }

  /**
   * Protected request helper for all /api/v1 routes.
   */
  async request(route, { method = 'GET', body, signal } = {}) {
    let response;
    try {
      response = await fetch(`${this.baseURL}/api/v1${route}`, {
        method,
        signal,
        cache: 'no-store',
        headers: {
          Authorization: `Bearer ${this.token}`,
          ...(body === undefined ? {} : { 'Content-Type': 'application/json' }),
        },
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch (err) {
      if (err.name === 'AbortError') throw err;
      throw new Error(
        'Cannot reach NEXUS backend. Confirm the Python server is running and CORS allows this origin (http://127.0.0.1:5173).'
      );
    }

    const result = await response.json().catch(() => ({}));

    if (!response.ok) {
      let message;
      if (typeof result.detail === 'string') {
        message = result.detail;
      } else if (Array.isArray(result.detail)) {
        message = result.detail
          .map((x) => `${(x.loc || []).join('.')}: ${x.type || 'invalid'}`)
          .join('; ');
      } else {
        message = `Request failed (${response.status})`;
      }

      const error = new Error(message);
      error.status = response.status;
      error.detail = result.detail;
      error.analysis_complete = result.analysis_complete;
      throw error;
    }

    return result;
  }

  repos() {
    return this.request('/repositories');
  }

  register(path) {
    return this.request('/repositories', {
      method: 'POST',
      body: { path: String(path).trim() },
    });
  }

  status(id) {
    return this.request(`/repositories/${encodeURIComponent(id)}/status`);
  }

  changes(id) {
    return this.request(`/repositories/${encodeURIComponent(id)}/changes`);
  }

  stage(id, paths) {
    return this.request(`/repositories/${encodeURIComponent(id)}/stage`, {
      method: 'POST',
      body: { paths },
    });
  }

  check(id, options = {}) {
    const scope = options.scope === 'commits' ? 'commits' : 'staged';
    const body = scope === 'commits'
      ? {
          scope: 'commits',
          base: options.base ? String(options.base).trim() : null,
          tip: options.tip ? String(options.tip).trim() : 'HEAD',
        }
      : { scope: 'staged' };

    return this.request(`/repositories/${encodeURIComponent(id)}/check`, {
      method: 'POST',
      body,
    });
  }

  why(id, path, line, ref = 'HEAD') {
    return this.request(`/repositories/${encodeURIComponent(id)}/why`, {
      method: 'POST',
      body: {
        path: String(path).trim(),
        line: Number(line),
        ref: String(ref).trim() || 'HEAD',
      },
    });
  }

  message(id) {
    return this.request(`/repositories/${encodeURIComponent(id)}/commit-message`, {
      method: 'POST',
    });
  }

  secrets(id) {
    return this.request(`/repositories/${encodeURIComponent(id)}/secrets`, {
      method: 'POST',
    });
  }

  forecast(id) {
    return this.request(`/repositories/${encodeURIComponent(id)}/forecast`, {
      method: 'POST',
    });
  }

  hooks(id, chainExisting = false) {
    return this.request(`/repositories/${encodeURIComponent(id)}/hooks`, {
      method: 'POST',
      body: { chain_existing: Boolean(chainExisting) },
    });
  }

  ingest(id, repository, limit = 40, refresh = false) {
    return this.request(`/repositories/${encodeURIComponent(id)}/ingest`, {
      method: 'POST',
      body: {
        repository: String(repository).trim(),
        limit: Number(limit),
        refresh: Boolean(refresh),
      },
    });
  }

  job(jobID) {
    return this.request(`/jobs/${encodeURIComponent(jobID)}`);
  }
}
