/** Browser client. Keep the bearer token in memory, never in a public build. */
export class PrecedentAPI {
  constructor(baseURL, token) {
    this.baseURL = baseURL.replace(/\/$/, "");
    this.token = token;
  }
  async request(path, {method = "GET", body, signal} = {}) {
    const response = await fetch(`${this.baseURL}/api/v1${path}`, {
      method, signal, cache: "no-store",
      headers: {Authorization: `Bearer ${this.token}`, ...(body === undefined ? {} : {"Content-Type": "application/json"})},
      ...(body === undefined ? {} : {body: JSON.stringify(body)}),
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(typeof result.detail === "string" ? result.detail : "Invalid API request");
      error.status = response.status;
      error.details = result.detail;
      throw error;
    }
    return result;
  }
  repositories() { return this.request("/repositories"); }
  register(path) { return this.request("/repositories", {method: "POST", body: {path}}); }
  status(id) { return this.request(`/repositories/${encodeURIComponent(id)}/status`); }
  changes(id) { return this.request(`/repositories/${encodeURIComponent(id)}/changes`); }
  action(id, name, body) { return this.request(`/repositories/${encodeURIComponent(id)}/${name}`, {method: "POST", body}); }
  check(id, options = {}) { return this.action(id, "check", options); }
  why(id, path, line, ref = "HEAD") { return this.action(id, "why", {path, line, ref}); }
  commitMessage(id) { return this.action(id, "commit-message"); }
  secrets(id) { return this.action(id, "secrets"); }
  forecast(id) { return this.action(id, "forecast"); }
  stage(id, paths) { return this.action(id, "stage", {paths}); }
  installHooks(id, chainExisting = false) { return this.action(id, "hooks", {chain_existing: chainExisting}); }
  ingest(id, repository, {limit = 40, refresh = false} = {}) { return this.action(id, "ingest", {repository, limit, refresh}); }
  job(id, signal) { return this.request(`/jobs/${encodeURIComponent(id)}`, {signal}); }
  async waitForJob(id, {signal, onProgress = () => {}, interval = 1000, timeout = 300000} = {}) {
    const deadline = Date.now() + timeout;
    while (Date.now() < deadline) {
      signal?.throwIfAborted();
      const job = await this.job(id, signal);
      onProgress(job);
      if (job.status === "succeeded") return job.result;
      if (["failed", "interrupted"].includes(job.status)) throw new Error(job.error || job.status);
      await new Promise(resolve => setTimeout(resolve, interval));
    }
    throw new Error("Polling timed out. Server job may still be running; poll its ID again.");
  }
}
