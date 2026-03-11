"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { getSession, SessionUser } from "@/lib/session";

interface Props {
  children: (user: SessionUser) => React.ReactNode;
}

export default function AuthGuard({ children }: Props) {
  const router = useRouter();
  const [user, setUser] = useState<SessionUser | null>(null);

  useEffect(() => {
    const session = getSession();
    if (!session) {
      router.replace("/login");
    } else {
      setUser(session);
    }
  }, [router]);

  if (!user) return <div className="loading">Checking session…</div>;
  return <>{children(user)}</>;
}
