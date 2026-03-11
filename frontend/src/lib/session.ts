/**
 * JWT session utilities — token stored in localStorage (MVP).
 */

const TOKEN_KEY = "access_token";

export interface SessionUser {
  uid: number;
  cid: number;
  role: "ADMIN" | "ANALYST" | "VIEWER";
  sub: string; // email
  exp: number;
}

export function saveToken(token: string): void {
  if (typeof window !== "undefined") {
    localStorage.setItem(TOKEN_KEY, token);
  }
}

export function getToken(): string | null {
  if (typeof window === "undefined") return null;
  return localStorage.getItem(TOKEN_KEY);
}

export function clearToken(): void {
  if (typeof window !== "undefined") {
    localStorage.removeItem(TOKEN_KEY);
  }
}

export function getSession(): SessionUser | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(atob(token.split(".")[1]));
    if (payload.exp * 1000 < Date.now()) {
      clearToken();
      return null;
    }
    return payload as SessionUser;
  } catch {
    return null;
  }
}

export function isAuthenticated(): boolean {
  return getSession() !== null;
}

export function canUpload(role: string): boolean {
  return role === "ADMIN" || role === "ANALYST";
}
