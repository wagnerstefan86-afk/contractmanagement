"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import AuthGuard from "@/components/AuthGuard";
import Nav from "@/components/Nav";
import { SessionUser } from "@/lib/session";
import { uploadContract } from "@/lib/api";

const ALLOWED = [".pdf", ".docx", ".txt"];
const MAX_MB = 50;

function UploadContent({ user }: { user: SessionUser }) {
  const router = useRouter();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [dragOver, setDragOver] = useState(false);

  if (user.role === "VIEWER") {
    return (
      <div className="page">
        <Nav user={user} />
        <main className="main">
          <div className="error-box">Viewers cannot upload contracts.</div>
        </main>
      </div>
    );
  }

  function validateFile(f: File): string {
    const ext = "." + f.name.split(".").pop()?.toLowerCase();
    if (!ALLOWED.includes(ext)) return `Unsupported format. Allowed: ${ALLOWED.join(", ")}`;
    if (f.size > MAX_MB * 1024 * 1024) return `File exceeds ${MAX_MB} MB limit.`;
    return "";
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const f = e.target.files?.[0] ?? null;
    if (f) {
      const err = validateFile(f);
      if (err) { setError(err); setFile(null); return; }
    }
    setFile(f);
    setError("");
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const f = e.dataTransfer.files[0];
    if (!f) return;
    const err = validateFile(f);
    if (err) { setError(err); return; }
    setFile(f);
    setError("");
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!file) { setError("Please select a file."); return; }
    setLoading(true);
    setError("");
    try {
      const contract = await uploadContract(file);
      router.push(`/contracts/${contract.contract_id}`);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Upload failed.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="page">
      <Nav user={user} />
      <main className="main">
        <div className="page-header">
          <h1>Upload contract</h1>
          <Link href="/contracts" className="btn btn-sm btn-outline">← Back</Link>
        </div>

        {error && <div className="error-box">{error}</div>}

        <div className="upload-card">
          <form onSubmit={handleSubmit}>
            <div
              className={`drop-zone${dragOver ? " drop-zone--active" : ""}${file ? " drop-zone--has-file" : ""}`}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
            >
              {file ? (
                <div className="drop-zone-file">
                  <span className="drop-zone-icon">📄</span>
                  <span className="drop-zone-name">{file.name}</span>
                  <span className="drop-zone-size">
                    ({(file.size / 1024 / 1024).toFixed(2)} MB)
                  </span>
                  <button
                    type="button"
                    className="btn btn-sm btn-ghost"
                    onClick={() => setFile(null)}
                  >Remove</button>
                </div>
              ) : (
                <>
                  <span className="drop-zone-icon">📂</span>
                  <p>Drag &amp; drop a contract here, or</p>
                  <label className="btn btn-outline btn-sm upload-label">
                    Choose file
                    <input
                      type="file"
                      accept=".pdf,.docx,.txt"
                      onChange={handleFileChange}
                      hidden
                    />
                  </label>
                  <p className="drop-zone-hint">PDF, DOCX, or TXT — up to {MAX_MB} MB</p>
                </>
              )}
            </div>

            <button
              type="submit"
              className="btn btn-primary btn-full"
              disabled={!file || loading}
            >
              {loading ? "Uploading…" : "Upload & ingest"}
            </button>
          </form>
        </div>
      </main>
    </div>
  );
}

export default function UploadPage() {
  return <AuthGuard>{(user) => <UploadContent user={user} />}</AuthGuard>;
}
