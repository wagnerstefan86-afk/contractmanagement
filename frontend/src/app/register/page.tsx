"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { register } from "@/lib/api";

export default function RegisterPage() {
  const router = useRouter();
  const [form, setForm] = useState({
    email: "", password: "", name: "", customer_id: "",
  });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  function handleChange(e: React.ChangeEvent<HTMLInputElement>) {
    setForm((f) => ({ ...f, [e.target.name]: e.target.value }));
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    const cid = parseInt(form.customer_id, 10);
    if (isNaN(cid) || cid < 1) {
      setError("Customer ID must be a positive integer.");
      return;
    }
    setLoading(true);
    try {
      await register(form.email, form.password, form.name, cid);
      router.push("/login?registered=1");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Registration failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-page">
      <div className="auth-card">
        <h1>ContractAI</h1>
        <h2>Create account</h2>
        {error && <div className="error-box">{error}</div>}
        <form onSubmit={handleSubmit}>
          <div className="field">
            <label htmlFor="name">Full name</label>
            <input id="name" name="name" type="text" value={form.name}
              onChange={handleChange} required autoFocus />
          </div>
          <div className="field">
            <label htmlFor="email">Email</label>
            <input id="email" name="email" type="email" value={form.email}
              onChange={handleChange} required />
          </div>
          <div className="field">
            <label htmlFor="password">Password <span className="hint">(min 8 chars)</span></label>
            <input id="password" name="password" type="password" value={form.password}
              onChange={handleChange} required minLength={8} />
          </div>
          <div className="field">
            <label htmlFor="customer_id">
              Customer / Tenant ID
              <span className="hint"> (ask your admin)</span>
            </label>
            <input id="customer_id" name="customer_id" type="number" value={form.customer_id}
              onChange={handleChange} required min={1} />
          </div>
          <button type="submit" className="btn btn-primary btn-full" disabled={loading}>
            {loading ? "Creating account…" : "Create account"}
          </button>
        </form>
        <p className="auth-footer">
          Already have an account? <Link href="/login">Sign in</Link>
        </p>
      </div>
    </div>
  );
}
