import React, { useEffect, useRef, useState } from 'react';
import { createRoot } from 'react-dom/client';
import {
  AlertCircle,
  ArrowRight,
  BookOpen,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clipboard,
  Clock,
  Code,
  CornerDownRight,
  Database,
  ExternalLink,
  FileCode,
  FileSearch,
  FileText,
  GitBranch,
  GitCommit,
  GitPullRequest,
  Info,
  KeyRound,
  Layers,
  Link,
  Loader2,
  Lock,
  Menu,
  Plus,
  RefreshCw,
  Search,
  Settings,
  Shield,
  ShieldAlert,
  ShieldCheck,
  Sparkles,
  Terminal,
  Trash2,
  X
} from 'lucide-react';
import { NexusAPI } from './api';
import './styles.css';

const DEFAULT_BASE_URL = 'http://127.0.0.1:8000';

const NAV_GROUPS = [
  {
    title: 'Workspace',
    items: [
      { id: 'overview', label: 'Overview', icon: Layers },
      { id: 'changes', label: 'Staged Changes', icon: FileCode },
      { id: 'check', label: 'Fence Check', icon: ShieldCheck },
      { id: 'history', label: 'Code History (Why?)', icon: BookOpen },
    ],
  },
  {
    title: 'Intelligence',
    items: [
      { id: 'secrets', label: 'Secret Scanner', icon: Lock },
      { id: 'commit', label: 'Commit Message', icon: GitCommit },
      { id: 'forecast', label: 'Review Forecast', icon: GitPullRequest },
    ],
  },
  {
    title: 'Management',
    items: [
      { id: 'settings', label: 'Ingestion & Hooks', icon: Settings },
    ],
  },
];

function shortSha(value, n = 8) {
  const str = String(value ?? '');
  return str.length > n ? str.slice(0, n) : str;
}

function verdictTone(v) {
  const s = String(v ?? '').toUpperCase();
  if (s === 'RED') return 'red';
  if (s === 'YELLOW') return 'yellow';
  if (s === 'GREEN') return 'green';
  return 'muted';
}

function formatAILabel(ai) {
  if (!ai) return 'Not analyzed';
  if (ai.status === 'completed') {
    return ai.cached ? 'Gemini · Cached AI result' : 'Gemini · Generated';
  }
  if (ai.status === 'blocked') {
    return `AI blocked for safety (${ai.reason || 'suspected credential'})`;
  }
  if (ai.status === 'unavailable') {
    return `AI unavailable — basic output (${ai.reason || 'quota or error'})`;
  }
  if (ai.status === 'disabled') {
    return 'Basic-only mode (AI disabled)';
  }
  if (ai.status === 'not_applicable') {
    return 'No changes to analyze';
  }
  return `AI: ${String(ai.status)}`;
}

function formatDate(val) {
  if (!val) return 'Never';
  const d = new Date(val);
  return Number.isNaN(d.getTime()) ? String(val) : d.toLocaleString();
}

function App() {
  // Session authentication - kept strictly in React memory
  const [baseURL, setBaseURL] = useState(DEFAULT_BASE_URL);
  const [token, setToken] = useState('');
  const [connected, setConnected] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [connectionError, setConnectionError] = useState('');

  // Repositories & Active Selection
  const [repos, setRepos] = useState([]);
  const [selectedID, setSelectedID] = useState('');
  const [section, setSection] = useState('overview');

  // Repository Data
  const [status, setStatus] = useState(null);
  const [changes, setChanges] = useState(null);
  const [results, setResults] = useState({});

  // Action States & Concurrency Control
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  // Registration modal
  const [showAddRepo, setShowAddRepo] = useState(false);
  const [newRepoPath, setNewRepoPath] = useState('');

  // Staging
  const [pathsToStage, setPathsToStage] = useState('');

  // Fence Check
  const [checkScope, setCheckScope] = useState('staged');
  const [commitBase, setCommitBase] = useState('main');
  const [commitTip, setCommitTip] = useState('HEAD');

  // Code History / Why
  const [whyPath, setWhyPath] = useState('');
  const [whyLine, setWhyLine] = useState('1');
  const [whyRef, setWhyRef] = useState('HEAD');

  // Ingestion
  const [ingestRepo, setIngestRepo] = useState('');
  const [ingestLimit, setIngestLimit] = useState('40');
  const [refreshIngestion, setRefreshIngestion] = useState(false);
  const [activeJob, setActiveJob] = useState(null);

  // Hooks
  const [chainHooks, setChainHooks] = useState(false);

  // UI state
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Refs for tracking in-flight operations and timer cleanup
  const apiRef = useRef(null);
  const jobPollTimer = useRef(null);
  const selectedIDRef = useRef('');

  useEffect(() => {
    selectedIDRef.current = selectedID;
  }, [selectedID]);

  // Cleanup polling on unmount
  useEffect(() => {
    return () => {
      if (jobPollTimer.current) clearInterval(jobPollTimer.current);
    };
  }, []);

  const selectedRepo = repos.find((r) => String(r.id) === String(selectedID));
  const repoBasename = selectedRepo?.path
    ? selectedRepo.path.replace(/\\/g, '/').split('/').filter(Boolean).pop()
    : 'Select repository';

  function clearAlerts() {
    setError('');
    setNotice('');
  }

  function handleReposList(items, preferID) {
    setRepos(items);
    const candidate = String(
      preferID ||
      (items.some((r) => String(r.id) === String(selectedIDRef.current))
        ? selectedIDRef.current
        : items[0]?.id || '')
    );
    selectedIDRef.current = candidate;
    setSelectedID(candidate);
  }

  // Connect to backend
  async function handleConnect(e) {
    e?.preventDefault();
    setConnecting(true);
    setConnectionError('');
    clearAlerts();

    const client = new NexusAPI(baseURL.trim(), token.trim());
    try {
      // First check public health endpoint
      try {
        await client.health();
      } catch {
        // Continue to repos; if health check fails due to proxy or path, auth call will report exact status
      }

      // Fetch registered repositories to validate bearer token
      const data = await client.repos();
      apiRef.current = client;
      setConnected(true);
      handleReposList(data.repositories || [], '');
      setNotice('Connected to NEXUS backend.');
    } catch (err) {
      setConnectionError(err.message);
    } finally {
      setConnecting(false);
    }
  }

  // Disconnect & wipe in-memory token and state
  function handleDisconnect() {
    if (jobPollTimer.current) {
      clearInterval(jobPollTimer.current);
      jobPollTimer.current = null;
    }
    apiRef.current = null;
    setToken('');
    setConnected(false);
    setRepos([]);
    setSelectedID('');
    selectedIDRef.current = '';
    setStatus(null);
    setChanges(null);
    setResults({});
    setActiveJob(null);
    clearAlerts();
  }

  /**
   * Sequential Refresh Flow
   * IMPORTANT CONCURRENCY FIX:
   * The backend holds a per-repository lock. Never request status and changes
   * concurrently with Promise.all. Await status, then await changes.
   */
  async function refresh(repoID = selectedID) {
    if (!apiRef.current) return;
    if (!repoID) {
      try {
        const r = await apiRef.current.repos();
        handleReposList(r.repositories || []);
      } catch (err) {
        setError(err.message);
      }
      return;
    }

    setBusy('refresh');
    clearAlerts();

    try {
      // Sequential requests to prevent backend per-repository lock contention (409)
      const s = await apiRef.current.status(repoID);
      const c = await apiRef.current.changes(repoID);
      const r = await apiRef.current.repos();

      if (selectedIDRef.current !== String(repoID)) return;
      setStatus(s);
      setChanges(c);
      handleReposList(r.repositories || [], repoID);
    } catch (err) {
      if (err.status === 409) {
        setError('Repository operation is in progress on the backend machine. Please wait for the current operation to complete.');
      } else {
        setError(err.message);
        setStatus(null);
        setChanges(null);
      }
    } finally {
      setBusy('');
    }
  }

  // Auto-refresh when active repository selection changes
  useEffect(() => {
    if (!connected || !selectedID) {
      setStatus(null);
      setChanges(null);
      return;
    }
    setResults({});
    setPathsToStage('');
    setActiveJob(null);
    clearAlerts();
    refresh(selectedID);
  }, [selectedID, connected]);

  // Register new repository
  async function handleRegisterRepo(e) {
    e.preventDefault();
    if (!apiRef.current || busy) return;
    clearAlerts();
    setBusy('register');

    try {
      const added = await apiRef.current.register(newRepoPath.trim());
      const r = await apiRef.current.repos();
      handleReposList(r.repositories || [], added.id);
      setShowAddRepo(false);
      setNewRepoPath('');
      setNotice(`Repository registered: ${added.path || added.id}`);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy('');
    }
  }

  // Stage paths
  async function handleStage() {
    if (!apiRef.current || !selectedID || busy) return;
    const paths = pathsToStage
      .split('\n')
      .map((p) => p.trim())
      .filter(Boolean);

    if (!paths.length) return;
    clearAlerts();
    setBusy('stage');

    try {
      await apiRef.current.stage(selectedID, paths);
      setNotice(`Staged ${paths.length} file path(s).`);
      setPathsToStage('');
      await refresh(selectedID);
    } catch (err) {
      if (err.status === 409) {
        setError('Repository operation is in progress on the backend machine. Please wait.');
      } else {
        setError(err.message);
      }
    } finally {
      setBusy('');
    }
  }

  // Run intelligence action
  async function runAction(name, customBody) {
    if (!apiRef.current || !selectedID || busy) return;
    clearAlerts();
    setBusy(name);

    try {
      let data;
      if (name === 'check') {
        const opts = customBody || (
          checkScope === 'commits'
            ? { scope: 'commits', base: commitBase.trim() || null, tip: commitTip.trim() || 'HEAD' }
            : { scope: 'staged' }
        );
        data = await apiRef.current.check(selectedID, opts);
      } else if (name === 'why') {
        data = await apiRef.current.why(selectedID, whyPath, Number(whyLine), whyRef);
      } else if (name === 'commit') {
        data = await apiRef.current.message(selectedID);
      } else if (name === 'secrets') {
        data = await apiRef.current.secrets(selectedID);
      } else if (name === 'forecast') {
        data = await apiRef.current.forecast(selectedID);
      }

      setResults((prev) => ({ ...prev, [name]: data }));
    } catch (err) {
      setResults((prev) => ({ ...prev, [name]: null }));
      if (err.status === 409) {
        setError('Repository operation is in progress on the backend machine.');
      } else {
        setError(err.message);
      }
    } finally {
      setBusy('');
    }
  }

  // Install Git Hooks
  async function handleInstallHooks() {
    if (!apiRef.current || !selectedID || busy) return;
    const confirmed = window.confirm(
      'Install pre-push and prepare-commit-msg hooks in this repository on the backend machine?\n\n' +
      'Note: Hooks execute locally on the backend host. Hooks are advisory and can be bypassed in Git.'
    );
    if (!confirmed) return;

    clearAlerts();
    setBusy('hooks');

    try {
      const res = await apiRef.current.hooks(selectedID, chainHooks);
      setNotice(`Installed Git hooks on backend machine (${res.installed?.join(', ') || 'pre-push, prepare-commit-msg'}).`);
    } catch (err) {
      if (err.status === 409) {
        setError('Repository operation is in progress on the backend machine.');
      } else {
        setError(err.message);
      }
    } finally {
      setBusy('');
    }
  }

  // Ingest GitHub history
  async function handleIngest(e) {
    e.preventDefault();
    if (!apiRef.current || !selectedID || busy) return;
    clearAlerts();
    setBusy('ingest');

    try {
      const res = await apiRef.current.ingest(
        selectedID,
        ingestRepo.trim(),
        Number(ingestLimit),
        refreshIngestion
      );
      const jobID = res.job_id;
      setActiveJob({ job_id: jobID, status: 'queued' });

      if (jobPollTimer.current) clearInterval(jobPollTimer.current);

      async function pollJob() {
        if (!apiRef.current) return true;
        try {
          const current = await apiRef.current.job(jobID);
          setActiveJob(current);

          if (['succeeded', 'failed', 'interrupted'].includes(current.status)) {
            clearInterval(jobPollTimer.current);
            jobPollTimer.current = null;
            setBusy('');

            if (current.status === 'succeeded') {
              setNotice(`GitHub history ingestion completed (${current.result?.selected_commits ?? 0} commits).`);
              await refresh(selectedID);
            } else {
              setError(current.error || `Ingestion job ${current.status}.`);
            }
            return true;
          }
          return false;
        } catch (err) {
          clearInterval(jobPollTimer.current);
          jobPollTimer.current = null;
          setBusy('');
          setError(err.message);
          return true;
        }
      }

      const doneImmediately = await pollJob();
      if (!doneImmediately && !jobPollTimer.current) {
        jobPollTimer.current = setInterval(pollJob, 1800);
      }
    } catch (err) {
      setBusy('');
      if (err.status === 409) {
        setError('Repository operation is in progress on the backend machine. If an ingestion job is already running, wait for it to complete.');
      } else {
        setError(err.message);
      }
    }
  }

  const isBusy = Boolean(busy);
  const checkResult = results.check;
  const checkFindings = checkResult?.findings || [];
  const redCount = checkFindings.filter(
    (f) => String(f.severity || f.level || '').toUpperCase() === 'RED'
  ).length;
  const yellowCount = checkFindings.filter(
    (f) => String(f.severity || f.level || '').toUpperCase() === 'YELLOW'
  ).length;

  return (
    <div className="app-shell">
      {/* Sidebar Navigation */}
      <aside className={`sidebar ${mobileMenuOpen ? 'open' : ''}`}>
        <div className="brand">
          <div className="brand-logo">
            <Terminal size={18} />
          </div>
          <div>
            <div className="brand-name">
              NEXUS<span className="brand-dot">.</span>
            </div>
            <div className="brand-sub">Git Precedent & Security Gate</div>
          </div>
          <button
            type="button"
            className="mobile-close"
            onClick={() => setMobileMenuOpen(false)}
            aria-label="Close menu"
          >
            <X size={18} />
          </button>
        </div>

        <div className="workspace-label">Repository Workspace</div>
        <div className="repository-select-box">
          <div className="repository-select">
            <GitBranch size={15} />
            <select
              aria-label="Select registered repository"
              value={selectedID}
              onChange={(e) => setSelectedID(e.target.value)}
              disabled={!connected || isBusy}
            >
              <option value="">
                {connected ? 'Select a repository' : 'Backend disconnected'}
              </option>
              {repos.map((r) => (
                <option key={r.id} value={r.id}>
                  {r.path ? r.path.replace(/\\/g, '/').split('/').filter(Boolean).pop() : r.id}
                </option>
              ))}
            </select>
            <ChevronDown size={14} />
          </div>

          <button
            type="button"
            className="add-repo-btn"
            onClick={() => {
              setShowAddRepo(true);
              setMobileMenuOpen(false);
            }}
            disabled={!connected || isBusy}
          >
            <Plus size={14} /> Register Repository Path
          </button>
        </div>

        <nav>
          {NAV_GROUPS.map((group) => (
            <div className="nav-group" key={group.title}>
              <div className="nav-heading">{group.title}</div>
              {group.items.map((item) => {
                const Icon = item.icon;
                const isActive = section === item.id;
                return (
                  <button
                    type="button"
                    key={item.id}
                    className={`nav-link ${isActive ? 'active' : ''}`}
                    onClick={() => {
                      setSection(item.id);
                      setMobileMenuOpen(false);
                      clearAlerts();
                    }}
                  >
                    <Icon size={16} />
                    <span>{item.label}</span>
                    {item.id === 'check' && checkResult?.verdict && (
                      <span className={`nav-status ${verdictTone(checkResult.verdict)}`} />
                    )}
                  </button>
                );
              })}
            </div>
          ))}
        </nav>

        <div className="sidebar-bottom">
          <div className="sidebar-status-indicator">
            <span className={`pulse ${connected ? 'on' : ''}`} />
            <span>{connected ? 'CONNECTED' : 'DISCONNECTED'}</span>
          </div>
          <div className="sidebar-target-url" title={baseURL}>
            {connected ? baseURL : 'No backend connection'}
          </div>
          <span className="sidebar-badge">v0.3.1 Contract</span>
        </div>
      </aside>

      {/* Main App Layout */}
      <div className="main-shell">
        <header className="topbar">
          <div className="topbar-crumb">
            <button
              type="button"
              className="menu-toggle"
              onClick={() => setMobileMenuOpen(true)}
              aria-label="Open menu"
            >
              <Menu size={18} />
            </button>
            <span>NEXUS</span>
            <ChevronRight size={14} />
            <strong>
              {NAV_GROUPS.flatMap((g) => g.items).find((i) => i.id === section)?.label || 'Console'}
            </strong>
          </div>

          <div className="topbar-right">
            <div className={`connection-pill ${connected ? 'connected' : ''}`}>
              <span className={`pulse ${connected ? 'on' : ''}`} />
              <span>{connected ? 'API Online' : 'Offline'}</span>
            </div>
            {connected && (
              <button
                type="button"
                className="btn ghost"
                title="Refresh repository state sequentially"
                onClick={() => refresh()}
                disabled={isBusy}
              >
                <RefreshCw size={14} className={busy === 'refresh' ? 'spin' : ''} />
                <span>Refresh</span>
              </button>
            )}
          </div>
        </header>

        <main className="content">
          {/* Connection Screen */}
          {!connected ? (
            <div className="login-container">
              <form className="login-card" onSubmit={handleConnect}>
                <div className="login-header">
                  <Terminal size={20} />
                  <h1>Connect to NEXUS Backend</h1>
                </div>
                <p className="login-description">
                  Connect to your local or trusted-host FastAPI backend companion. Inspect repositories that exist on the backend machine.
                </p>

                <label htmlFor="base-url-input">BACKEND SERVICE URL</label>
                <input
                  id="base-url-input"
                  required
                  type="url"
                  value={baseURL}
                  onChange={(e) => setBaseURL(e.target.value)}
                  placeholder="http://127.0.0.1:8000"
                />

                <label htmlFor="token-input">API BEARER TOKEN</label>
                <input
                  id="token-input"
                  required
                  type="password"
                  autoComplete="off"
                  value={token}
                  onChange={(e) => setToken(e.target.value)}
                  placeholder="Paste token from ~/.precedent-web/api-token"
                />

                {connectionError && (
                  <div className="alert error" style={{ marginTop: '14px' }}>
                    <AlertCircle size={16} />
                    <span>{connectionError}</span>
                  </div>
                )}

                <button
                  type="submit"
                  className="btn primary big"
                  style={{ width: '100%', marginTop: '16px' }}
                  disabled={connecting}
                >
                  {connecting ? <Loader2 size={16} className="spin" /> : <Link size={16} />}
                  <span>{connecting ? 'Connecting…' : 'Connect to Backend'}</span>
                </button>

                <div className="login-security-notice">
                  <strong>Security notice:</strong> The bearer token is held in React session memory only. It is never persisted to localStorage, cookies, or logs. GEMINI_API_KEY and GITHUB_TOKEN remain strictly on the backend host.
                </div>
              </form>
            </div>
          ) : (
            <>
              {/* Connected View Header */}
              <div className="page-head">
                <div>
                  <h1>
                    {NAV_GROUPS.flatMap((g) => g.items).find((i) => i.id === section)?.label}
                  </h1>
                  <p>
                    {section === 'overview' && 'Status, coverage, and health of the active Git repository on the backend machine.'}
                    {section === 'changes' && 'View files currently staged in Git and stage additional repository-relative paths.'}
                    {section === 'check' && 'Combined fence check for staged changes or commit ranges. Returns one RED/YELLOW/GREEN verdict.'}
                    {section === 'history' && 'Trace committed lines to blamed commits and historical review precedent.'}
                    {section === 'secrets' && 'Detect suspected credentials in staged changes before they leave your machine.'}
                    {section === 'commit' && 'Suggest a conventional commit message grounded in repository changes and evidence.'}
                    {section === 'forecast' && 'Anticipate review concerns based on sampled repository history. Advisory only.'}
                    {section === 'settings' && 'Manage GitHub history ingestion and install local Git pre-push and commit-message hooks.'}
                  </p>
                </div>

                <div className="head-actions">
                  <span className="repo-pill" title={selectedRepo?.path || ''}>
                    <GitBranch size={13} />
                    <span>{repoBasename}</span>
                  </span>
                  {status?.synthetic && (
                    <span className="synthetic-pill" title="This repository contains synthetic demo fixture data">
                      Synthetic Demo
                    </span>
                  )}
                </div>
              </div>

              {/* Status Alerts */}
              {error && (
                <div className="alert error">
                  <AlertCircle size={16} />
                  <span>{error}</span>
                  <button type="button" className="alert-close" onClick={() => setError('')}>
                    <X size={14} />
                  </button>
                </div>
              )}
              {notice && (
                <div className="alert success">
                  <CheckCircle2 size={16} />
                  <span>{notice}</span>
                  <button type="button" className="alert-close" onClick={() => setNotice('')}>
                    <X size={14} />
                  </button>
                </div>
              )}

              {/* No repository selected empty state */}
              {!selectedID ? (
                <div className="panel">
                  <div className="empty-box">
                    <GitBranch size={32} />
                    <h3>No Repository Selected</h3>
                    <p>
                      Select an existing repository from the sidebar dropdown or register an absolute path located inside PRECEDENT_REPO_ROOTS on the backend machine.
                    </p>
                    <button
                      type="button"
                      className="btn primary"
                      style={{ marginTop: '16px' }}
                      onClick={() => setShowAddRepo(true)}
                    >
                      <Plus size={14} /> Register Repository
                    </button>
                  </div>
                </div>
              ) : (
                <>
                  {/* OVERVIEW SECTION */}
                  {section === 'overview' && (
                    <>
                      <div className="metrics-row">
                        <div className="metric-card">
                          <div className="metric-caption">Fence Check</div>
                          <div className={`metric-value ${verdictTone(checkResult?.verdict)}`}>
                            {checkResult?.verdict || 'NOT RUN'}
                          </div>
                          <div className="metric-detail">
                            {checkResult
                              ? checkResult.push_allowed
                                ? 'Push allowed by check'
                                : 'Push blocked (RED)'
                              : 'Run Fence Check to evaluate'}
                          </div>
                        </div>

                        <div className="metric-card">
                          <div className="metric-caption">Staged Files</div>
                          <div className="metric-value">
                            {changes?.files?.length ?? '—'}
                          </div>
                          <div className="metric-detail">Files in Git staging index</div>
                        </div>

                        <div className="metric-card">
                          <div className="metric-caption">Blocking Findings</div>
                          <div className={`metric-value ${redCount > 0 ? 'red' : ''}`}>
                            {checkResult ? redCount : '—'}
                          </div>
                          <div className="metric-detail">
                            {checkResult ? `${yellowCount} warning(s)` : 'Awaiting check'}
                          </div>
                        </div>

                        <div className="metric-card">
                          <div className="metric-caption">Covered Commits</div>
                          <div className="metric-value">
                            {status?.covered_commits ?? '—'}
                          </div>
                          <div className="metric-detail">
                            {status?.synthetic ? 'Synthetic fixture' : 'Ingested Git commits'}
                          </div>
                        </div>
                      </div>

                      <div className="two-column">
                        <div className="panel">
                          <div className="panel-heading">
                            <h2>Repository Details</h2>
                            <span className="count-badge">LIVE STATUS</span>
                          </div>
                          <div className="info-row">
                            <span>Repository Path</span>
                            <strong className="mono" title={selectedRepo?.path}>{selectedRepo?.path || '—'}</strong>
                          </div>
                          <div className="info-row">
                            <span>HEAD Revision</span>
                            <strong className="mono">{status?.head ? shortSha(status.head, 12) : '—'}</strong>
                          </div>
                          <div className="info-row">
                            <span>GitHub Remote</span>
                            <strong>{status?.github_repository || 'Not linked'}</strong>
                          </div>
                          <div className="info-row">
                            <span>Ingestion State</span>
                            <strong>{status?.ingestion || 'not started'}</strong>
                          </div>
                          <div className="info-row">
                            <span>Last Ingested</span>
                            <strong>{formatDate(status?.last_ingested)}</strong>
                          </div>
                          <div className="info-row">
                            <span>Dataset Integrity</span>
                            <strong className={status?.synthetic ? 'yellow' : 'green'}>
                              {status?.synthetic ? 'Synthetic demonstration fixture' : 'Verified Git history'}
                            </strong>
                          </div>
                        </div>

                        <div className="panel">
                          <div className="panel-heading">
                            <h2>Backend AI Configuration</h2>
                            <span className="count-badge">GEMINI INTEGRATION</span>
                          </div>
                          <div className="info-row">
                            <span>Provider</span>
                            <strong>{status?.ai?.provider || 'Gemini'}</strong>
                          </div>
                          <div className="info-row">
                            <span>Configured Model</span>
                            <strong className="mono">{status?.ai?.model || 'gemini-3.5-flash-lite'}</strong>
                          </div>
                          <div className="info-row">
                            <span>AI Feature Gate</span>
                            <strong className={status?.ai?.enabled ? 'green' : 'yellow'}>
                              {status?.ai?.enabled ? 'Enabled (default)' : 'Disabled (PRECEDENT_AI=0)'}
                            </strong>
                          </div>
                          <div className="info-row">
                            <span>API Key Detected</span>
                            <strong className={status?.ai?.key_configured ? 'green' : 'yellow'}>
                              {status?.ai?.key_configured ? 'Configured on backend' : 'Missing on backend'}
                            </strong>
                          </div>
                          <p className="muted small" style={{ marginTop: '12px' }}>
                            A configured key indicates GEMINI_API_KEY was found in the backend environment. Inference success is reported dynamically when actions execute.
                          </p>
                        </div>
                      </div>

                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Staged Files</h2>
                          <button
                            type="button"
                            className="btn ghost"
                            onClick={() => setSection('changes')}
                          >
                            Manage Staging <ArrowRight size={14} />
                          </button>
                        </div>
                        <FileList files={changes?.files || []} />
                      </div>
                    </>
                  )}

                  {/* STAGED CHANGES SECTION */}
                  {section === 'changes' && (
                    <div className="two-column">
                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Staged Changes in Index</h2>
                          <span className="count-badge">{changes?.files?.length ?? 0} files</span>
                        </div>
                        <p className="muted">
                          These files are currently staged on the backend repository. Raw secret-bearing diff contents are intentionally withheld by the API to prevent accidental credential leakage.
                        </p>
                        <FileList files={changes?.files || []} />
                      </div>

                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Stage Files by Path</h2>
                          <Terminal size={16} />
                        </div>
                        <p className="muted">
                          Enter repository-relative paths, one per line. This executes <code>git add</code> on the backend repository.
                        </p>
                        <textarea
                          rows={6}
                          placeholder={'src/parser.py\ntests/test_parser.py'}
                          value={pathsToStage}
                          onChange={(e) => setPathsToStage(e.target.value)}
                        />
                        <button
                          type="button"
                          className="btn primary"
                          style={{ marginTop: '12px' }}
                          disabled={isBusy || !pathsToStage.trim()}
                          onClick={handleStage}
                        >
                          {busy === 'stage' ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                          <span>Stage Named Paths</span>
                        </button>
                      </div>
                    </div>
                  )}

                  {/* FENCE CHECK SECTION */}
                  {section === 'check' && (
                    <>
                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Fence Check Parameters</h2>
                          <ShieldCheck size={16} />
                        </div>
                        <p className="muted">
                          Runs deterministic guard analysis, credential detection, test coverage inspection, and optional Gemini interpretation.
                        </p>

                        <div className="segmented-control">
                          <button
                            type="button"
                            className={checkScope === 'staged' ? 'selected' : ''}
                            onClick={() => setCheckScope('staged')}
                          >
                            Staged Changes
                          </button>
                          <button
                            type="button"
                            className={checkScope === 'commits' ? 'selected' : ''}
                            onClick={() => setCheckScope('commits')}
                          >
                            Commit Range
                          </button>
                        </div>

                        {checkScope === 'commits' && (
                          <div className="form-grid">
                            <div>
                              <label htmlFor="commit-base-input">BASE REF</label>
                              <input
                                id="commit-base-input"
                                value={commitBase}
                                onChange={(e) => setCommitBase(e.target.value)}
                                placeholder="main"
                              />
                            </div>
                            <div>
                              <label htmlFor="commit-tip-input">TIP REF</label>
                              <input
                                id="commit-tip-input"
                                value={commitTip}
                                onChange={(e) => setCommitTip(e.target.value)}
                                placeholder="HEAD"
                              />
                            </div>
                          </div>
                        )}

                        <div style={{ marginTop: '14px' }}>
                          <button
                            type="button"
                            className="btn primary big"
                            disabled={isBusy}
                            onClick={() => runAction('check')}
                          >
                            {busy === 'check' ? <Loader2 size={16} className="spin" /> : <ShieldCheck size={16} />}
                            <span>{busy === 'check' ? 'Analyzing Changes…' : 'Run Fence Check'}</span>
                          </button>
                        </div>
                      </div>

                      {checkResult && (
                        <>
                          <div className={`verdict-banner ${verdictTone(checkResult.verdict)}`}>
                            <div>
                              <div className={`verdict-tag ${verdictTone(checkResult.verdict)}`}>
                                {checkResult.verdict === 'RED' && <ShieldAlert size={28} />}
                                {checkResult.verdict === 'YELLOW' && <AlertCircle size={28} />}
                                {checkResult.verdict === 'GREEN' && <ShieldCheck size={28} />}
                                <span>VERDICT: {checkResult.verdict}</span>
                              </div>
                              <p className="muted small" style={{ margin: '4px 0 0' }}>
                                Scope: {checkResult.scope} · Analysis status: {checkResult.analysis_status || 'completed'}
                              </p>
                            </div>
                            <div className={`verdict-push-status ${checkResult.push_allowed ? 'allowed' : 'blocked'}`}>
                              {checkResult.push_allowed ? 'PUSH ALLOWED' : 'PUSH BLOCKED'}
                            </div>
                          </div>

                          <div className="panel">
                            <div className="panel-heading">
                              <h2>Findings</h2>
                              <span className="count-badge">{checkFindings.length} findings</span>
                            </div>
                            <FindingsList findings={checkFindings} />
                          </div>

                          {checkResult.ai && (
                            <AIOutputSection ai={checkResult.ai} />
                          )}

                          <DataDetails data={checkResult} label="Fence Check Raw Payload" />
                        </>
                      )}
                    </>
                  )}

                  {/* CODE HISTORY / WHY SECTION */}
                  {section === 'history' && (
                    <div className="two-column">
                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Line History Query</h2>
                          <FileSearch size={16} />
                        </div>
                        <p className="muted">
                          Identify the last modifying commit for a line and correlate it with cached PR reviews. Line numbers refer to HEAD, not unstaged working copy edits.
                        </p>

                        <form onSubmit={(e) => { e.preventDefault(); runAction('why'); }}>
                          <label htmlFor="why-path-input">FILE PATH (RELATIVE TO REPOSITORY ROOT)</label>
                          <input
                            id="why-path-input"
                            required
                            value={whyPath}
                            onChange={(e) => setWhyPath(e.target.value)}
                            placeholder="src/parser.py"
                          />

                          <div className="form-grid">
                            <div>
                              <label htmlFor="why-line-input">LINE NUMBER</label>
                              <input
                                id="why-line-input"
                                type="number"
                                min="1"
                                required
                                value={whyLine}
                                onChange={(e) => setWhyLine(e.target.value)}
                              />
                            </div>
                            <div>
                              <label htmlFor="why-ref-input">GIT REF</label>
                              <input
                                id="why-ref-input"
                                required
                                value={whyRef}
                                onChange={(e) => setWhyRef(e.target.value)}
                                placeholder="HEAD"
                              />
                            </div>
                          </div>

                          <button
                            type="submit"
                            className="btn primary"
                            style={{ marginTop: '16px' }}
                            disabled={isBusy}
                          >
                            {busy === 'why' ? <Loader2 size={14} className="spin" /> : <Search size={14} />}
                            <span>Explain Code Line</span>
                          </button>
                        </form>
                      </div>

                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Historical Explanation</h2>
                          {results.why?.mode && <span className="count-badge">{results.why.mode}</span>}
                        </div>

                        {results.why ? (
                          <>
                            <div className="ai-output-box">
                              <div className="ai-prose">{results.why.explanation || 'No explanation returned.'}</div>
                            </div>

                            <div style={{ marginTop: '14px' }}>
                              <div className="info-row">
                                <span>Blamed Commit</span>
                                <strong className="mono">{results.why.sha ? shortSha(results.why.sha, 12) : '—'}</strong>
                              </div>
                              <div className="info-row">
                                <span>Commit Summary</span>
                                <strong>{results.why.summary || results.why.message || '—'}</strong>
                              </div>
                              <div className="info-row">
                                <span>Author</span>
                                <strong>{results.why.author || '—'}</strong>
                              </div>
                              <div className="info-row">
                                <span>Author Date</span>
                                <strong>{results.why.author_date || '—'}</strong>
                              </div>
                            </div>

                            {results.why.note && (
                              <p className="muted small" style={{ marginTop: '10px' }}>
                                {results.why.note}
                              </p>
                            )}

                            {results.why.ai && <AIOutputSection ai={results.why.ai} />}
                            <DataDetails data={results.why.evidence} label="Retrieved Cached Evidence" />
                          </>
                        ) : (
                          <div className="empty-box">
                            <BookOpen size={28} />
                            <h3>No Line Query Executed</h3>
                            <p>Enter a file path and line number to retrieve commit blame and evidence.</p>
                          </div>
                        )}
                      </div>
                    </div>
                  )}

                  {/* SECRET SCANNER SECTION */}
                  {section === 'secrets' && (
                    <div className="panel">
                      <div className="panel-heading">
                        <h2>Staged Secret Scanner</h2>
                        <Lock size={16} />
                      </div>
                      <p className="muted">
                        Scans staged files for high-entropy credential patterns, API keys, private keys, and hardcoded authentication tokens. Suspected secret values are redacted locally to protect sensitive data.
                      </p>

                      <button
                        type="button"
                        className="btn primary"
                        disabled={isBusy}
                        onClick={() => runAction('secrets')}
                      >
                        {busy === 'secrets' ? <Loader2 size={14} className="spin" /> : <Lock size={14} />}
                        <span>Scan Staged Changes for Secrets</span>
                      </button>

                      {results.secrets && (
                        <div style={{ marginTop: '20px' }}>
                          <div className="panel-heading">
                            <h2>Findings</h2>
                            <span className="count-badge">
                              {results.secrets.findings?.length ?? 0} matches
                            </span>
                          </div>
                          <FindingsList findings={results.secrets.findings || []} />
                          <DataDetails data={results.secrets} label="Secret Scanner Payload" />
                        </div>
                      )}
                    </div>
                  )}

                  {/* COMMIT MESSAGE SECTION */}
                  {section === 'commit' && (
                    <div className="panel">
                      <div className="panel-heading">
                        <h2>Commit Message Assistant</h2>
                        <GitCommit size={16} />
                      </div>
                      <p className="muted">
                        Proposes a conventional Git commit message based on staged changes and recent repository conventions. The backend never commits or pushes automatically.
                      </p>

                      <button
                        type="button"
                        className="btn primary"
                        disabled={isBusy}
                        onClick={() => runAction('commit')}
                      >
                        {busy === 'commit' ? <Loader2 size={14} className="spin" /> : <GitCommit size={14} />}
                        <span>Generate Proposed Commit Message</span>
                      </button>

                      {results.commit && (
                        <div style={{ marginTop: '20px' }}>
                          <div className="panel-heading">
                            <h2>Suggested Message</h2>
                            <span className="count-badge">Mode: {results.commit.mode || 'standard'}</span>
                          </div>

                          <div className="ai-output-box">
                            <div className="ai-prose mono">{results.commit.message || 'No message generated.'}</div>
                          </div>

                          <div style={{ marginTop: '12px', display: 'flex', gap: '8px' }}>
                            <button
                              type="button"
                              className="btn ghost"
                              onClick={() => {
                                if (results.commit.message && navigator.clipboard) {
                                  navigator.clipboard.writeText(results.commit.message);
                                  setNotice('Commit message copied to clipboard.');
                                }
                              }}
                            >
                              <Clipboard size={14} /> Copy Message
                            </button>
                          </div>

                          {results.commit.ai && <AIOutputSection ai={results.commit.ai} />}
                          <DataDetails data={results.commit} label="Commit Assistant Response Payload" />
                        </div>
                      )}
                    </div>
                  )}

                  {/* REVIEW FORECAST SECTION */}
                  {section === 'forecast' && (
                    <div className="panel">
                      <div className="panel-heading">
                        <h2>Review Feedback Forecast</h2>
                        <GitPullRequest size={16} />
                      </div>
                      <p className="muted">
                        Identifies potential review concerns based on sampled repository history. Advisory evidence only; does not guarantee maintainer approval or absence of defects.
                      </p>

                      <button
                        type="button"
                        className="btn primary"
                        disabled={isBusy}
                        onClick={() => runAction('forecast')}
                      >
                        {busy === 'forecast' ? <Loader2 size={14} className="spin" /> : <GitPullRequest size={14} />}
                        <span>Generate Review Forecast</span>
                      </button>

                      {results.forecast && (
                        <div style={{ marginTop: '20px' }}>
                          <div className="panel-heading">
                            <h2>Forecast Findings</h2>
                            <span className="count-badge">
                              {results.forecast.findings?.length ?? 0} items
                            </span>
                          </div>
                          <FindingsList findings={results.forecast.findings || []} />
                          {results.forecast.ai && <AIOutputSection ai={results.forecast.ai} />}
                          <DataDetails data={results.forecast} label="Forecast Response Payload" />
                        </div>
                      )}
                    </div>
                  )}

                  {/* SETTINGS / INGESTION & HOOKS SECTION */}
                  {section === 'settings' && (
                    <div className="two-column">
                      <div className="panel">
                        <div className="panel-heading">
                          <h2>GitHub History Ingestion</h2>
                          <Database size={16} />
                        </div>
                        <p className="muted">
                          Ingest commit, PR, and review evidence from GitHub into the backend SQLite store. Requires backend internet access and optional GITHUB_TOKEN. Do not ingest real GitHub history into a synthetic demo fixture.
                        </p>

                        <form onSubmit={handleIngest}>
                          <label htmlFor="ingest-repo-input">GITHUB REPOSITORY (OWNER/REPO)</label>
                          <input
                            id="ingest-repo-input"
                            required
                            pattern="^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$"
                            value={ingestRepo}
                            onChange={(e) => setIngestRepo(e.target.value)}
                            placeholder="owner/repo"
                          />

                          <label htmlFor="ingest-limit-input">COMMIT SAMPLE LIMIT (1–1000)</label>
                          <input
                            id="ingest-limit-input"
                            type="number"
                            min="1"
                            max="1000"
                            required
                            value={ingestLimit}
                            onChange={(e) => setIngestLimit(e.target.value)}
                          />

                          <label className="check-label">
                            <input
                              type="checkbox"
                              checked={refreshIngestion}
                              onChange={(e) => setRefreshIngestion(e.target.checked)}
                            />
                            <span>Refresh previously cached commits</span>
                          </label>

                          <button
                            type="submit"
                            className="btn primary"
                            style={{ marginTop: '16px' }}
                            disabled={isBusy}
                          >
                            {busy === 'ingest' ? <Loader2 size={14} className="spin" /> : <Database size={14} />}
                            <span>Start History Ingestion</span>
                          </button>
                        </form>

                        {activeJob && (
                          <div className="ai-output-box" style={{ marginTop: '16px' }}>
                            <div className="info-row">
                              <span>Job ID</span>
                              <strong className="mono">{shortSha(activeJob.job_id, 12)}</strong>
                            </div>
                            <div className="info-row">
                              <span>Status</span>
                              <strong className={activeJob.status === 'succeeded' ? 'green' : activeJob.status === 'failed' ? 'red' : 'yellow'}>
                                {String(activeJob.status).toUpperCase()}
                              </strong>
                            </div>
                            <div className="info-row">
                              <span>Progress</span>
                              <span>{activeJob.progress || activeJob.message || 'Processing…'}</span>
                            </div>
                            {activeJob.error && (
                              <div className="alert error" style={{ marginTop: '10px' }}>
                                <AlertCircle size={14} />
                                <span>{activeJob.error}</span>
                              </div>
                            )}
                          </div>
                        )}
                      </div>

                      <div className="panel">
                        <div className="panel-heading">
                          <h2>Local Git Hooks</h2>
                          <Terminal size={16} />
                        </div>
                        <p className="muted">
                          Install <code>pre-push</code> and <code>prepare-commit-msg</code> hooks directly into the repository’s <code>.git/hooks</code> directory on the backend host.
                        </p>

                        <label className="check-label">
                          <input
                            type="checkbox"
                            checked={chainHooks}
                            onChange={(e) => setChainHooks(e.target.checked)}
                          />
                          <span>Chain existing hooks if already installed</span>
                        </label>

                        <button
                          type="button"
                          className="btn primary"
                          style={{ marginTop: '16px' }}
                          disabled={isBusy}
                          onClick={handleInstallHooks}
                        >
                          {busy === 'hooks' ? <Loader2 size={14} className="spin" /> : <Shield size={14} />}
                          <span>Install Hooks on Backend Host</span>
                        </button>

                        <div style={{ marginTop: '24px', paddingTop: '16px', borderTop: '1px solid var(--color-border-muted)' }}>
                          <h3>Session Authentication</h3>
                          <p className="muted small">
                            Connected via in-memory token to <code>{baseURL}</code>. Disconnecting discards the bearer token.
                          </p>
                          <button
                            type="button"
                            className="btn danger"
                            onClick={handleDisconnect}
                          >
                            <Trash2 size={14} /> Disconnect Session
                          </button>
                        </div>
                      </div>
                    </div>
                  )}
                </>
              )}
            </>
          )}
        </main>

        <footer className="footer">
          <span>NEXUS · Developer Git Security Gate</span>
          <span>FastAPI companion · Grounded evidence</span>
        </footer>
      </div>

      {/* Register Repository Modal */}
      {showAddRepo && (
        <div
          className="modal-backdrop"
          onMouseDown={(e) => {
            if (e.target === e.currentTarget) setShowAddRepo(false);
          }}
        >
          <form className="modal-content" onSubmit={handleRegisterRepo}>
            <div className="panel-heading">
              <h2>Register Existing Repository</h2>
              <button
                type="button"
                className="alert-close"
                onClick={() => setShowAddRepo(false)}
              >
                <X size={16} />
              </button>
            </div>
            <p className="muted">
              Supply the absolute path to a Git repository located on the backend machine. The directory must reside inside the backend’s <code>PRECEDENT_REPO_ROOTS</code>.
            </p>

            <label htmlFor="repo-path-input">ABSOLUTE REPOSITORY ROOT PATH</label>
            <input
              id="repo-path-input"
              required
              autoFocus
              value={newRepoPath}
              onChange={(e) => setNewRepoPath(e.target.value)}
              placeholder="C:\\path\\to\\trusted-repo or /home/user/trusted-repo"
            />

            <div className="modal-actions">
              <button
                type="button"
                className="btn ghost"
                onClick={() => setShowAddRepo(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="btn primary"
                disabled={isBusy || !newRepoPath.trim()}
              >
                {busy === 'register' ? <Loader2 size={14} className="spin" /> : <Plus size={14} />}
                <span>Register Path</span>
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  );
}

// Subcomponents for presentation

function FileList({ files }) {
  if (!Array.isArray(files) || !files.length) {
    return (
      <div className="empty-box">
        <CheckCircle2 size={24} />
        <h3>No Staged Files Found</h3>
        <p>Stage changes with <code>git add</code> in your terminal or use the staging panel.</p>
      </div>
    );
  }

  return (
    <div className="file-list">
      {files.map((file, i) => (
        <div className="file-row" key={file.path || i}>
          <div className="file-name">
            <FileCode size={15} />
            <span title={file.path}>{file.path}</span>
          </div>
          <div className="file-stats">
            <span className="added">+{file.added_lines ?? 0}</span>
            <span className="removed">−{file.removed_lines ?? 0}</span>
            {file.binary && <span className="binary">BINARY</span>}
          </div>
        </div>
      ))}
    </div>
  );
}

function FindingsList({ findings }) {
  if (!Array.isArray(findings) || !findings.length) {
    return (
      <div className="empty-box">
        <CheckCircle2 size={24} />
        <h3>No Findings Reported</h3>
        <p>No risks were flagged by this scan. (Note: Heuristic checks do not guarantee the absence of all defects.)</p>
      </div>
    );
  }

  return (
    <div className="findings-list">
      {findings.map((f, i) => {
        const severity = String(f.severity || f.level || f.verdict || 'INFO').toUpperCase();
        const tone = verdictTone(severity);
        const title = f.message || f.description || f.reason || f.title || 'Finding';
        return (
          <div className="finding-item" key={i}>
            <span className={`finding-severity ${tone}`}>{severity}</span>
            <div className="finding-body">
              <div className="finding-message">{String(title)}</div>
              <div className="finding-meta">
                {f.path && <span>File: <code>{f.path}</code></span>}
                {f.line && <span>Line: {f.line}</span>}
                {f.category && <span>Category: {f.category}</span>}
              </div>
              {f.details && (
                <div className="finding-details">
                  {typeof f.details === 'string' ? f.details : JSON.stringify(f.details)}
                </div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function AIOutputSection({ ai }) {
  if (!ai) return null;
  return (
    <div className="ai-output-box" style={{ marginTop: '16px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '8px' }}>
        <h3 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: '6px' }}>
          <Sparkles size={15} /> Gemini AI Analysis
        </h3>
        <span className="ai-status-tag">{formatAILabel(ai)}</span>
      </div>

      {ai.text ? (
        <div className="ai-prose">{ai.text}</div>
      ) : (
        <div className="muted small">
          {ai.reason || 'No generated AI interpretation was returned for this check.'}
        </div>
      )}

      {Array.isArray(ai.citations) && ai.citations.length > 0 && (
        <div className="citations-group">
          <div className="citations-title">Evidence Citations</div>
          <div className="citations-list">
            {ai.citations.map((c, i) => (
              <span className="citation-pill" key={i}>
                {typeof c === 'string' ? c : JSON.stringify(c)}
              </span>
            ))}
          </div>
        </div>
      )}

      <div className="ai-disclaimer">
        AI output is advisory interpretation. Deterministic checks and evidence records provide authoritative safety boundaries.
      </div>
    </div>
  );
}

function DataDetails({ data, label = 'View Structured Backend Response' }) {
  if (!data) return null;
  return (
    <details className="data-details">
      <summary>
        <ChevronDown size={14} />
        <span>{label}</span>
      </summary>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </details>
  );
}

const rootElement = document.getElementById('root');
if (rootElement) {
  createRoot(rootElement).render(<App />);
}
