"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { getLLMConfig, LLMConfigOut } from "@/lib/api";

function LLMSettingsContent({ user }: { user: SessionUser }) {
  const isAdmin = user.role === "ADMIN";
  const [config,  setConfig]  = useState<LLMConfigOut | null>(null);
  const [loading, setLoading] = useState(true);
  const [error,   setError]   = useState("");

  useEffect(() => {
    if (!isAdmin) return;
    getLLMConfig()
      .then(setConfig)
      .catch((err: Error) => setError(err.message))
      .finally(() => setLoading(false));
  }, [isAdmin]);

  if (!isAdmin) {
    return (
      <div className="page">
        <Nav user={user} />
        <main className="main">
          <div className="page-header">
            <div>
              <div className="breadcrumb">Settings</div>
              <h1>LLM Configuration</h1>
            </div>
          </div>
          <div className="warn-box">ADMIN access required to view LLM configuration.</div>
        </main>
      </div>
    );
  }

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <div className="breadcrumb">
              <Link href="/settings/customer-profile">Settings</Link>
            </div>
            <h1>LLM Configuration</h1>
            <p className="page-subtitle">
              Current AI/LLM provider settings for the analysis pipeline.
              Changes require updating environment variables and restarting the backend service.
            </p>
          </div>
        </div>

        {error && <div className="error-box">{error}</div>}
        {loading && <div className="loading">Loading LLM configuration…</div>}

        {!loading && config && (
          <>
            <div className="profile-section">
              <h2 className="profile-section-title">Pipeline Status</h2>
              <div className="stats-grid" style={{ gridTemplateColumns: "repeat(auto-fill, minmax(200px, 1fr))" }}>
                <div className="stat-card">
                  <div className="stat-label">LLM enabled</div>
                  <div className="stat-value">
                    <span className={config.llm_enabled ? "badge badge--green" : "badge badge--gray"}>
                      {config.llm_enabled ? "Enabled" : "Disabled"}
                    </span>
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">API key</div>
                  <div className="stat-value">
                    <span className={config.key_configured ? "badge badge--green" : "badge badge--red"}>
                      {config.key_configured ? "Configured" : "Not configured"}
                    </span>
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Provider</div>
                  <div className="stat-value" style={{ fontSize: "0.9rem", fontWeight: 600 }}>
                    {config.provider}
                  </div>
                </div>
                <div className="stat-card">
                  <div className="stat-label">Request timeout</div>
                  <div className="stat-value" style={{ fontSize: "0.9rem" }}>
                    {config.timeout_seconds}s
                  </div>
                </div>
              </div>
            </div>

            <div className="profile-section">
              <h2 className="profile-section-title">Model</h2>
              <table className="detail-table">
                <tbody>
                  <tr>
                    <th>Configured model</th>
                    <td className="mono">{config.model ?? <span className="text-muted">(using provider default)</span>}</td>
                  </tr>
                  <tr>
                    <th>Effective model</th>
                    <td className="mono">{((config as unknown as Record<string, unknown>).effective_model as string) ?? config.model ?? "—"}</td>
                  </tr>
                </tbody>
              </table>
            </div>

            {!config.llm_enabled && (
              <div className="warn-box">
                <strong>LLM is disabled.</strong>{" "}
                The pipeline runs in deterministic (rule-based) mode only.
                Set <code>LLM_ENABLED=true</code> and configure an API key to enable AI-augmented analysis.
              </div>
            )}

            {config.llm_enabled && !config.key_configured && (
              <div className="warn-box">
                <strong>API key not configured.</strong>{" "}
                LLM is enabled but no API key is set. Set <code>LLM_API_KEY</code>,{" "}
                <code>ANTHROPIC_API_KEY</code>, or <code>OPENAI_API_KEY</code> in the backend environment.
              </div>
            )}

            {config.llm_enabled && config.key_configured && (
              <div className="info-box">
                LLM analysis is active. Stages 4.5, 5, and 8 use AI-augmented analysis
                with deterministic fallback on timeout or error.
              </div>
            )}

            <div className="profile-section">
              <h2 className="profile-section-title">How to change configuration</h2>
              <p className="profile-section-desc">
                LLM settings are controlled via environment variables.
                Update the backend container environment and restart:
              </p>
              <table className="detail-table">
                <thead>
                  <tr><th>Variable</th><th>Current effect</th><th>Example values</th></tr>
                </thead>
                <tbody>
                  <tr>
                    <td className="mono">LLM_ENABLED</td>
                    <td>{config.llm_enabled ? "true — AI enabled" : "false — deterministic only"}</td>
                    <td className="mono">true / false</td>
                  </tr>
                  <tr>
                    <td className="mono">LLM_PROVIDER</td>
                    <td>{config.provider}</td>
                    <td className="mono">anthropic / openai</td>
                  </tr>
                  <tr>
                    <td className="mono">LLM_MODEL</td>
                    <td>{config.model ? config.model : "using provider default"}</td>
                    <td className="mono">claude-opus-4-6 / gpt-4o</td>
                  </tr>
                  <tr>
                    <td className="mono">LLM_API_KEY</td>
                    <td>{config.key_configured ? "configured" : "not set"}</td>
                    <td className="mono">sk-... / ant-...</td>
                  </tr>
                  <tr>
                    <td className="mono">ANTHROPIC_API_KEY</td>
                    <td>provider-specific key for Anthropic</td>
                    <td className="mono">ant-...</td>
                  </tr>
                  <tr>
                    <td className="mono">OPENAI_API_KEY</td>
                    <td>provider-specific key for OpenAI</td>
                    <td className="mono">sk-...</td>
                  </tr>
                  <tr>
                    <td className="mono">LLM_TIMEOUT_SECONDS</td>
                    <td>{config.timeout_seconds}s per request</td>
                    <td className="mono">30 / 60 / 120</td>
                  </tr>
                </tbody>
              </table>
            </div>
          </>
        )}
      </main>
    </div>
  );
}

export default function LLMSettingsPage() {
  return <AuthGuard>{(user) => <LLMSettingsContent user={user} />}</AuthGuard>;
}
