"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getLLMConfig,
  updateLLMConfig,
  testLLMConfig,
  LLMConfigOut,
  LLMTestResult,
} from "@/lib/api";

// ── Status badge helpers ───────────────────────────────────────────────────────

function YesNo({ v }: { v: boolean }) {
  return v
    ? <span className="badge badge--green">Yes</span>
    : <span className="badge badge--red">No</span>;
}

function OnOff({ v }: { v: boolean }) {
  return v
    ? <span className="badge badge--green">On</span>
    : <span className="badge badge--gray">Off</span>;
}

// ── Main page component ────────────────────────────────────────────────────────

function LLMSettingsContent({ user }: { user: SessionUser }) {
  const isAdmin = user.role === "ADMIN";

  const [config,  setConfig]  = useState<LLMConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");          // page-level load error only

  // Toggle state (separate from provider form)
  const [toggleError,  setToggleError]  = useState("");
  const [toggleSaved,  setToggleSaved]  = useState(false);

  // Provider form state
  const [formError,    setFormError]    = useState("");
  const [formSaved,    setFormSaved]    = useState(false);

  // Edit form state
  const [editProvider,  setEditProvider]  = useState("");
  const [editModel,     setEditModel]     = useState("");
  const [editApiKey,    setEditApiKey]    = useState("");
  const [editTimeout,   setEditTimeout]   = useState("");
  const [saving,        setSaving]        = useState(false);

  // Connection test state
  const [testResult,  setTestResult]  = useState<LLMTestResult | null>(null);
  const [testing,     setTesting]     = useState(false);

  useEffect(() => {
    getLLMConfig()
      .then((cfg) => {
        setConfig(cfg);
        setEditProvider(cfg.provider ?? "anthropic");
        setEditModel(cfg.model ?? "");
        setEditTimeout(String(cfg.timeout_seconds ?? 60));
      })
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  // ── Toggle app-level switch ──────────────────────────────────────────────────
  async function handleToggle(newVal: boolean) {
    if (!config) return;
    setSaving(true); setToggleError(""); setToggleSaved(false);
    try {
      const updated = await updateLLMConfig({ app_llm_enabled: newVal });
      setConfig(updated);
      setToggleSaved(true);
      setTimeout(() => setToggleSaved(false), 3000);
    } catch (e: unknown) {
      setToggleError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  // ── Save provider / model / key / timeout ────────────────────────────────────
  async function handleSaveProviderConfig(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setFormError(""); setFormSaved(false); setTestResult(null);
    try {
      const patch: Record<string, unknown> = {
        provider:        editProvider,
        model:           editModel.trim(),
        timeout_seconds: parseInt(editTimeout, 10) || 60,
      };
      // Only send api_key if non-empty (empty = keep existing key)
      if (editApiKey.trim()) {
        patch.api_key = editApiKey.trim();
      }
      const updated = await updateLLMConfig(patch);
      setConfig(updated);
      setEditApiKey("");   // clear after save — never echo back
      setFormSaved(true);
      setTimeout(() => setFormSaved(false), 4000);
    } catch (e: unknown) {
      setFormError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  // ── Connection test ──────────────────────────────────────────────────────────
  async function handleTest() {
    setTesting(true); setTestResult(null); setError("");
    try {
      const result = await testLLMConfig();
      setTestResult(result);
    } catch (e: unknown) {
      setTestResult({
        success: false,
        status: "unknown_error",
        message: e instanceof Error ? e.message : "Request failed.",
        provider: null,
        model: null,
      });
    } finally {
      setTesting(false);
    }
  }

  // ── Render ───────────────────────────────────────────────────────────────────

  if (loading) return (
    <div className="page"><Nav user={user} /><main className="main"><div className="loading">Loading…</div></main></div>
  );

  if (!config) return (
    <div className="page"><Nav user={user} />
      <main className="main">
        {error && <div className="error-box">{error}</div>}
      </main>
    </div>
  );

  const testStatusClass = testResult
    ? testResult.success ? "success-box" : "error-box"
    : "";

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">

        <div className="page-header">
          <div>
            <h1>LLM Configuration</h1>
            <p className="page-subtitle">AI-assisted analysis settings — admin only</p>
          </div>
        </div>

        {error && <div className="error-box" style={{ marginBottom: "1rem" }}>{error}</div>}

        {/* ── Effective status overview ─────────────────────────────────────── */}
        <div className="section">
          <h2>Effective AI status</h2>
          <div className="stats-grid">
            <div className="stat-card">
              <div className="stat-label">Effective AI analysis</div>
              <div className="stat-value">
                {config.effective_enabled
                  ? <span className="badge badge--green">ENABLED</span>
                  : <span className="badge badge--red">DISABLED</span>}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">System capability (LLM_ENABLED)</div>
              <div className="stat-value"><YesNo v={config.system_llm_enabled} /></div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Provider configured</div>
              <div className="stat-value"><YesNo v={config.provider_configured} /></div>
            </div>
            <div className="stat-card">
              <div className="stat-label">App-level switch</div>
              <div className="stat-value"><OnOff v={config.app_llm_enabled} /></div>
            </div>
            <div className="stat-card">
              <div className="stat-label">API key stored</div>
              <div className="stat-value"><YesNo v={config.key_configured} /></div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Active provider</div>
              <div className="stat-value mono">{config.provider}</div>
            </div>
            <div className="stat-card">
              <div className="stat-label">Active model</div>
              <div className="stat-value mono">{config.effective_model}</div>
            </div>
          </div>

          {config.app_llm_enabled && !config.system_llm_enabled && (
            <div className="warn-box" style={{ marginTop: "1rem" }}>
              <strong>System capability unavailable.</strong>{" "}
              App switch is ON but <code>LLM_ENABLED=false</code> — AI will not run.
            </div>
          )}
          {config.app_llm_enabled && config.system_llm_enabled && !config.key_configured && (
            <div className="warn-box" style={{ marginTop: "1rem" }}>
              <strong>No API key configured.</strong>{" "}
              App switch is ON but no API key is stored. Save a key below.
            </div>
          )}
          {!config.app_llm_enabled && (
            <div className="info-box" style={{ marginTop: "1rem" }}>
              AI analysis is <strong>disabled</strong> — pipeline runs in deterministic mode.
            </div>
          )}
          {config.effective_enabled && (
            <div className="success-box" style={{ marginTop: "1rem" }}>
              AI-assisted analysis is <strong>active</strong> — next run will use{" "}
              <strong>{config.provider}</strong> / <strong>{config.effective_model}</strong>.
            </div>
          )}
        </div>

        {/* ── App-level on/off toggle (admin only) ─────────────────────────── */}
        {isAdmin && (
          <div className="section">
            <h2>Operational toggle</h2>
            <p className="page-subtitle" style={{ marginBottom: "1rem" }}>
              Enable or disable AI-assisted analysis for all users without changing provider settings.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
              <button
                className={`btn ${config.app_llm_enabled ? "btn-primary" : "btn-outline"}`}
                onClick={() => handleToggle(true)}
                disabled={saving || config.app_llm_enabled}
              >
                Enable AI analysis
              </button>
              <button
                className={`btn ${!config.app_llm_enabled ? "btn-primary" : "btn-outline"}`}
                onClick={() => handleToggle(false)}
                disabled={saving || !config.app_llm_enabled}
              >
                Disable AI analysis
              </button>
              {saving && <span className="text-muted" style={{ fontSize: "0.85rem" }}>Saving…</span>}
              {toggleSaved && !saving && (
                <span style={{ color: "var(--color-success, #16a34a)", fontSize: "0.85rem", fontWeight: 500 }}>
                  ✓ Saved
                </span>
              )}
            </div>
            {toggleError && (
              <div className="error-box" style={{ marginTop: "0.75rem" }}>{toggleError}</div>
            )}
          </div>
        )}

        {/* ── Provider / model / API key configuration (admin only) ────────── */}
        {isAdmin && (
          <div className="section">
            <h2>Provider configuration</h2>
            <p className="page-subtitle" style={{ marginBottom: "1.25rem" }}>
              These settings are stored in the database and override environment variables.
              The API key is stored server-side and never returned to the browser.
            </p>

            <form onSubmit={handleSaveProviderConfig} style={{ maxWidth: "480px" }}>

              {/* Provider selector */}
              <div style={{ marginBottom: "1rem" }}>
                <label className="form-label" htmlFor="provider">LLM Provider</label>
                <select
                  id="provider"
                  className="form-input"
                  value={editProvider}
                  onChange={(e) => {
                    setEditProvider(e.target.value);
                    setEditModel("");  // reset model when provider changes
                  }}
                >
                  <option value="anthropic">Anthropic (Claude)</option>
                  <option value="openai">OpenAI (GPT)</option>
                </select>
              </div>

              {/* Model name */}
              <div style={{ marginBottom: "1rem" }}>
                <label className="form-label" htmlFor="model">Model</label>
                <input
                  id="model"
                  className="form-input"
                  type="text"
                  placeholder={editProvider === "anthropic" ? "claude-opus-4-6" : "gpt-4o"}
                  value={editModel}
                  onChange={(e) => setEditModel(e.target.value)}
                />
                <div className="form-hint">
                  Leave blank to use the provider default.{" "}
                  {editProvider === "anthropic"
                    ? "e.g. claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5"
                    : "e.g. gpt-4o, gpt-4o-mini, gpt-4-turbo"}
                </div>
              </div>

              {/* API key */}
              <div style={{ marginBottom: "1rem" }}>
                <label className="form-label" htmlFor="apikey">
                  API Key
                  {config.key_configured && (
                    <span
                      className="badge badge--green"
                      style={{ marginLeft: "0.5rem", fontSize: "0.7rem" }}
                    >
                      key stored ••••••••
                    </span>
                  )}
                </label>
                <input
                  id="apikey"
                  className="form-input"
                  type="password"
                  autoComplete="new-password"
                  placeholder={
                    config.key_configured
                      ? "Leave blank to keep existing key"
                      : "Paste API key here…"
                  }
                  value={editApiKey}
                  onChange={(e) => setEditApiKey(e.target.value)}
                />
                <div className="form-hint">
                  {editProvider === "anthropic"
                    ? "Anthropic API key — starts with sk-ant-"
                    : "OpenAI API key — starts with sk-"}
                  {" "}Stored server-side, never returned to the browser.
                </div>
              </div>

              {/* Timeout */}
              <div style={{ marginBottom: "1.5rem" }}>
                <label className="form-label" htmlFor="timeout">Request timeout (seconds)</label>
                <input
                  id="timeout"
                  className="form-input"
                  type="number"
                  min={5}
                  max={300}
                  value={editTimeout}
                  onChange={(e) => setEditTimeout(e.target.value)}
                  style={{ width: "120px" }}
                />
              </div>

              <div style={{ display: "flex", gap: "0.75rem", alignItems: "center", flexWrap: "wrap" }}>
                <button type="submit" className="btn btn-primary" disabled={saving}>
                  {saving ? "Saving…" : "Save provider config"}
                </button>
                {formSaved && !saving && (
                  <span style={{ color: "var(--color-success, #16a34a)", fontSize: "0.85rem", fontWeight: 500 }}>
                    ✓ Settings saved
                  </span>
                )}
              </div>
              {formError && (
                <div className="error-box" style={{ marginTop: "0.75rem" }}>{formError}</div>
              )}
            </form>
          </div>
        )}

        {/* ── Connection test (admin only) ──────────────────────────────────── */}
        {isAdmin && (
          <div className="section">
            <h2>Connection test</h2>
            <p className="page-subtitle" style={{ marginBottom: "1rem" }}>
              Validates the configured provider and API key without running a full analysis.
            </p>

            <button
              className="btn btn-outline"
              onClick={handleTest}
              disabled={testing || !config.key_configured}
              title={!config.key_configured ? "Save an API key first" : undefined}
            >
              {testing ? "Testing connection…" : "Test provider connection"}
            </button>

            {testResult && (
              <div className={testStatusClass} style={{ marginTop: "1rem" }}>
                <strong>
                  {testResult.success
                    ? "✓ Connection successful"
                    : `✗ ${_statusLabel(testResult.status)}`}
                </strong>
                <br />
                <span style={{ fontSize: "0.875rem" }}>{testResult.message}</span>
                {testResult.provider && (
                  <div style={{ fontSize: "0.8rem", marginTop: "0.35rem", opacity: 0.8 }}>
                    Provider: {testResult.provider}
                    {testResult.model ? ` / ${testResult.model}` : ""}
                  </div>
                )}
              </div>
            )}
          </div>
        )}

        {/* ── How effective status is determined ───────────────────────────── */}
        <div className="section">
          <h2>How effective status is determined</h2>
          <div className="info-box">
            <strong>effective_enabled = system_llm_enabled AND provider_configured AND app_llm_enabled</strong>
            <br />
            <code>system_llm_enabled</code> is the server-side <code>LLM_ENABLED</code> env var.{" "}
            <code>provider_configured</code> is true when an API key is present (DB or env).{" "}
            The app-level toggle lets the admin pause AI analysis without touching infrastructure.
            When AI is disabled, the pipeline runs fully deterministic rule-based analysis.
          </div>
        </div>

      </main>
    </div>
  );
}

function _statusLabel(status: string): string {
  const labels: Record<string, string> = {
    auth_failed:          "Authentication failed",
    provider_unavailable: "Provider unavailable",
    invalid_model:        "Invalid model",
    missing_key:          "Missing API key",
    unknown_error:        "Unknown error",
  };
  return labels[status] ?? status;
}

export default function LLMSettingsPage() {
  return <AuthGuard>{(user) => <LLMSettingsContent user={user} />}</AuthGuard>;
}
