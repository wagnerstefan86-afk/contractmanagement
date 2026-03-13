"use client";

import { useEffect, useState } from "react";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import {
  getLLMSettings,
  updateLLMSettings,
  testLLMConnection,
  LLMSettingsOut,
  ApiError,
} from "@/lib/api";

// ── Constants ─────────────────────────────────────────────────────────────────

const PROVIDERS = ["anthropic", "openai"] as const;

const PROVIDER_LABELS: Record<string, string> = {
  anthropic: "Anthropic (Claude)",
  openai:    "OpenAI (GPT)",
};

const DEFAULT_MODELS: Record<string, string> = {
  anthropic: "claude-opus-4-6",
  openai:    "gpt-4o",
};

// ── Helpers ───────────────────────────────────────────────────────────────────

function extractErrors(err: unknown): string[] {
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.message);
      if (Array.isArray(parsed?.detail)) {
        return parsed.detail.map(
          (e: { loc: string[]; msg: string }) =>
            `${e.loc.slice(1).join(".")}: ${e.msg}`,
        );
      }
      if (typeof parsed?.detail === "string") return [parsed.detail];
    } catch {
      return [err.message];
    }
  }
  if (err instanceof Error) return [err.message];
  return ["An unexpected error occurred."];
}

// ── Main component ───────────────────────────────────────────────────────────

function LLMSettingsContent({ user }: { user: SessionUser }) {
  const isAdmin = user.role === "ADMIN";

  const [loading,    setLoading]    = useState(true);
  const [saving,     setSaving]     = useState(false);
  const [testing,    setTesting]    = useState(false);
  const [success,    setSuccess]    = useState(false);
  const [errors,     setErrors]     = useState<string[]>([]);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null);

  // Form state
  const [enabled,    setEnabled]    = useState(true);
  const [provider,   setProvider]   = useState("anthropic");
  const [model,      setModel]      = useState("");
  const [apiKey,     setApiKey]     = useState("");
  const [timeout,    setTimeout_]   = useState(60);
  const [maskedKey,  setMaskedKey]  = useState("");

  // ── Load ────────────────────────────────────────────────────────────────────

  useEffect(() => {
    getLLMSettings()
      .then((s: LLMSettingsOut) => {
        setEnabled(s.llm_enabled);
        setProvider(s.provider);
        setModel(s.model);
        setTimeout_(s.timeout_seconds);
        setMaskedKey(s.api_key_masked);
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 403) {
          setErrors(["Access denied. ADMIN role required."]);
        } else {
          setErrors(extractErrors(err));
        }
      })
      .finally(() => setLoading(false));
  }, []);

  // ── Save ────────────────────────────────────────────────────────────────────

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setErrors([]);
    setSuccess(false);
    setTestResult(null);
    setSaving(true);
    try {
      const saved = await updateLLMSettings({
        llm_enabled:     enabled,
        provider,
        model,
        api_key:         apiKey,
        timeout_seconds: timeout,
      });
      setMaskedKey(saved.api_key_masked);
      setApiKey("");
      setSuccess(true);
      window.setTimeout(() => setSuccess(false), 4000);
    } catch (err) {
      setErrors(extractErrors(err));
    } finally {
      setSaving(false);
    }
  }

  // ── Test connection ─────────────────────────────────────────────────────────

  async function handleTest() {
    setTestResult(null);
    setErrors([]);

    // Need an API key: either just typed one, or there's a saved one
    const keyToTest = apiKey || "";
    if (!keyToTest && !maskedKey) {
      setTestResult({ success: false, message: "Enter an API key first." });
      return;
    }
    if (!keyToTest) {
      setTestResult({ success: false, message: "Enter the API key to test. The saved key cannot be read back for security reasons." });
      return;
    }

    setTesting(true);
    try {
      const result = await testLLMConnection({
        provider,
        api_key:         keyToTest,
        model,
        timeout_seconds: timeout,
      });
      setTestResult({ success: result.success, message: result.message });
    } catch (err) {
      setTestResult({ success: false, message: extractErrors(err).join(" ") });
    } finally {
      setTesting(false);
    }
  }

  // ── Render ──────────────────────────────────────────────────────────────────

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <div>
            <div className="breadcrumb">Settings</div>
            <h1>LLM Configuration</h1>
            <p className="page-subtitle">
              Configure the AI provider used for contract analysis.
              When disabled, the pipeline runs fully deterministic (rule-based).
            </p>
          </div>
          <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-end", gap: "0.5rem" }}>
            {!isAdmin && (
              <span className="badge badge--gray">Read-only — ADMIN access required to edit</span>
            )}
          </div>
        </div>

        {loading && <div className="loading">Loading LLM settings…</div>}

        {!loading && (
          <form onSubmit={handleSave} className="profile-form">

            {/* Success banner */}
            {success && (
              <div className="success-box">
                LLM configuration saved. Changes take effect immediately.
              </div>
            )}

            {/* Validation errors */}
            {errors.length > 0 && (
              <div className="error-box">
                {errors.map((e, i) => <div key={i}>{e}</div>)}
              </div>
            )}

            {/* ── Section: General ───────────────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">General</h2>

              <div className="form-group">
                <label className="form-label form-label--check">
                  <input
                    type="checkbox"
                    checked={enabled}
                    onChange={(e) => { setEnabled(e.target.checked); setSuccess(false); }}
                    disabled={!isAdmin}
                  />
                  LLM enabled — use AI-augmented analysis
                </label>
              </div>
            </div>

            {/* ── Section: Provider ──────────────────────────────────── */}
            <div className="profile-section">
              <h2 className="profile-section-title">Provider</h2>

              <div className="form-row">
                <div className="form-group">
                  <label className="form-label" htmlFor="llm-provider">Provider</label>
                  <select
                    id="llm-provider"
                    className="form-select"
                    value={provider}
                    onChange={(e) => { setProvider(e.target.value); setSuccess(false); setTestResult(null); }}
                    disabled={!isAdmin}
                  >
                    {PROVIDERS.map((p) => (
                      <option key={p} value={p}>{PROVIDER_LABELS[p]}</option>
                    ))}
                  </select>
                </div>

                <div className="form-group">
                  <label className="form-label" htmlFor="llm-model">
                    Model
                  </label>
                  <input
                    id="llm-model"
                    className="form-input"
                    type="text"
                    value={model}
                    onChange={(e) => { setModel(e.target.value); setSuccess(false); }}
                    disabled={!isAdmin}
                    placeholder={`Default: ${DEFAULT_MODELS[provider] ?? ""}`}
                  />
                </div>
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="llm-api-key">
                  API Key
                </label>
                <input
                  id="llm-api-key"
                  className="form-input"
                  type="password"
                  value={apiKey}
                  onChange={(e) => { setApiKey(e.target.value); setSuccess(false); setTestResult(null); }}
                  disabled={!isAdmin}
                  placeholder={maskedKey ? `Current: ${maskedKey}` : "Enter API key"}
                  autoComplete="off"
                />
                {maskedKey && !apiKey && (
                  <span className="form-hint">Leave empty to keep the existing key.</span>
                )}
              </div>

              <div className="form-group">
                <label className="form-label" htmlFor="llm-timeout">
                  Timeout (seconds)
                </label>
                <input
                  id="llm-timeout"
                  className="form-input"
                  type="number"
                  min={1}
                  max={600}
                  value={timeout}
                  onChange={(e) => { setTimeout_(parseInt(e.target.value) || 60); setSuccess(false); }}
                  disabled={!isAdmin}
                  style={{ maxWidth: "12rem" }}
                />
              </div>
            </div>

            {/* ── Test connection ─────────────────────────────────────── */}
            {isAdmin && (
              <div className="profile-section">
                <h2 className="profile-section-title">Connection Test</h2>
                <p className="profile-section-desc">
                  Test the connection to the selected provider before saving.
                  Requires the API key to be entered above.
                </p>

                <button
                  type="button"
                  className="btn btn-secondary"
                  onClick={handleTest}
                  disabled={testing || saving}
                  style={{ marginBottom: "0.75rem" }}
                >
                  {testing ? "Testing…" : "Test connection"}
                </button>

                {testResult && (
                  <div className={testResult.success ? "success-box" : "error-box"}>
                    {testResult.message}
                  </div>
                )}
              </div>
            )}

            {/* ── Save button ────────────────────────────────────────── */}
            {isAdmin && (
              <div className="form-actions">
                <button
                  type="submit"
                  className="btn btn-primary"
                  disabled={saving || testing}
                >
                  {saving ? "Saving…" : "Save LLM settings"}
                </button>
                <span className="form-hint">
                  Changes take effect immediately for all subsequent analysis runs.
                </span>
              </div>
            )}
          </form>
        )}
      </main>
    </div>
  );
}

export default function LLMSettingsPage() {
  return (
    <AuthGuard>
      {(user) => <LLMSettingsContent user={user} />}
    </AuthGuard>
  );
}
