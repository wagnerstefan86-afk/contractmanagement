"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { clearToken, SessionUser } from "@/lib/session";

interface Props {
  user: SessionUser;
}

export default function Nav({ user }: Props) {
  const router = useRouter();

  function logout() {
    clearToken();
    router.push("/login");
  }

  const isAdmin   = user.role === "ADMIN";
  const canUpload = isAdmin || user.role === "ANALYST";

  return (
    <nav className="nav">
      <div className="nav-brand">
        <Link href="/dashboard">InfoSec Review</Link>
      </div>
      <div className="nav-links">
        <Link href="/dashboard">Dashboard</Link>
        <Link href="/reviews">Findings</Link>
        <Link href="/contracts">Contracts</Link>
        {canUpload && <Link href="/contracts/upload">Upload</Link>}
        <Link href="/settings/customer-profile">Settings</Link>
        {isAdmin && <Link href="/settings/llm">LLM Config</Link>}
      </div>
      <div className="nav-user">
        <span className={`role-badge role-badge--${user.role.toLowerCase()}`}>{user.role}</span>
        <span>{user.sub}</span>
        <button onClick={logout} className="btn btn-sm btn-ghost">Logout</button>
      </div>
    </nav>
  );
}
