"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { getLLMConfig, updateLLMConfig, LLMConfigOut } from "@/lib/api";

function LLMSettingsContent({ user }: { user: SessionUser }) {
  const [config,  setConfig]  = useState<LLMConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving,  setSaving]  = useState(false);
  const [error,   setError]   = useState("");
  const [saved,   setSaved]   = useState(false);

  useEffect(() => {
    getLLMConfig()
      .then(setConfig)
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, []);

  async function handleToggle(newVal: boolean) {
    if (!config) return;
    setSaving(true);
    setError("");
    setSaved(false);
    try {
      const updated = await updateLLMConfig(newVal);
      setConfig(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Save failed.");
    } finally {
      setSaving(false);
    }
  }

  const isAdmin = user.role === "ADMIN";

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

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <h1>LLM Configuration</h1>
            <p className="page-subtitle">AI-assisted analysis settings — admin controlled</p>
          </div>
        </div>

        {error && <div className="error-box" style={{ marginBottom: "1rem" }}>{error}</div>}
        {saved && <div className="success-box" style={{ marginBottom: "1rem" }}>Setting saved.</div>}

        {/* ── Effective status ──────────────────────────────────────────────── */}
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
              <div className="stat-label">System capability (env)</div>
              <div className="stat-value">
                {config.system_llm_enabled && config.key_configured
                  ? <span className="badge badge--green">Available</span>
                  : <span className="badge badge--red">Unavailable</span>}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">App-level switch (DB)</div>
              <div className="stat-value">
                {config.app_llm_enabled
                  ? <span className="badge badge--blue">On</span>
                  : <span className="badge badge--gray">Off</span>}
              </div>
            </div>
            <div className="stat-card">
              <div className="stat-label">API key configured</div>
              <div className="stat-value">
                {config.key_configured
                  ? <span className="badge badge--green">Yes</span>
                  : <span className="badge badge--red">No</span>}
              </div>
            </div>
          </div>

          {config.app_llm_enabled && !config.system_llm_enabled && (
            <div className="warn-box" style={{ marginTop: "1rem" }}>
              <strong>System capability unavailable.</strong>{" "}
              App switch is ON but LLM_ENABLED env var is false — AI analysis will not run.
            </div>
          )}
          {config.app_llm_enabled && config.system_llm_enabled && !config.key_configured && (
            <div className="warn-box" style={{ marginTop: "1rem" }}>
              <strong>No API key configured.</strong>{" "}
              App switch is ON but no API key is set. Pipeline will run in deterministic fallback mode.
            </div>
          )}
          {!config.app_llm_enabled && (
            <div className="info-box" style={{ marginTop: "1rem" }}>
              AI-assisted analysis is <strong>disabled at the app level</strong>.
              The pipeline will run in deterministic (rule-based) mode only.
            </div>
          )}
        </div>

        {/* ── App-level toggle ─────────────────────────────────────────────── */}
        {isAdmin && (
          <div className="section">
            <h2>Operational toggle</h2>
            <p className="page-subtitle" style={{ marginBottom: "1rem" }}>
              Enable or disable AI-assisted analysis for all users.
              This setting is stored in the database and takes effect on the next analysis run.
            </p>
            <div style={{ display: "flex", gap: "0.75rem", alignItems: "center" }}>
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
            </div>
          </div>
        )}

        {/* ── System configuration details ─────────────────────────────────── */}
        <div className="section">
          <h2>System configuration</h2>
          <p className="page-subtitle" style={{ marginBottom: "1rem" }}>
            These values come from environment variables and require a service restart to change.
          </p>
          <div className="table-scroll">
            <table className="table">
              <thead>
                <tr><th>Setting</th><th>Value</th><th>Source</th></tr>
              </thead>
              <tbody>
                <tr>
                  <td>LLM_ENABLED</td>
                  <td>{config.system_llm_enabled
                    ? <span className="badge badge--green">true</span>
                    : <span className="badge badge--red">false</span>}
                  </td>
                  <td className="text-muted">env var</td>
                </tr>
                <tr>
                  <td>Provider</td>
                  <td className="mono">{config.provider}</td>
                  <td className="text-muted">LLM_PROVIDER</td>
                </tr>
                <tr>
                  <td>Configured model</td>
                  <td className="mono">{config.model ?? <span className="text-muted">(using provider default)</span>}</td>
                  <td className="text-muted">LLM_MODEL</td>
                </tr>
                <tr>
                  <td>Effective model</td>
                  <td className="mono">{config.effective_model}</td>
                  <td className="text-muted">resolved</td>
                </tr>
                <tr>
                  <td>API key</td>
                  <td>{config.key_configured
                    ? <span className="badge badge--green">Configured ••••••••</span>
                    : <span className="badge badge--red">Not set</span>}
                  </td>
                  <td className="text-muted">LLM_API_KEY / ANTHROPIC_API_KEY / OPENAI_API_KEY</td>
                </tr>
                <tr>
                  <td>Request timeout</td>
                  <td>{config.timeout_seconds}s</td>
                  <td className="text-muted">LLM_TIMEOUT_SECONDS</td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>

        {/* ── How it works ─────────────────────────────────────────────────── */}
        <div className="section">
          <h2>How effective status is determined</h2>
          <div className="info-box">
            <strong>effective_enabled = system_capability AND app_setting</strong>
            <br />
            System capability requires both <code>LLM_ENABLED=true</code> and an API key to be set.
            The app-level switch (above) can further disable AI analysis without changing environment variables.
            When AI is disabled, the pipeline runs in fully deterministic rule-based mode with no external API calls.
          </div>
        </div>
      </main>
    </div>
  );
}

export default function LLMSettingsPage() {
  return <AuthGuard>{(user) => <LLMSettingsContent user={user} />}</AuthGuard>;
}
