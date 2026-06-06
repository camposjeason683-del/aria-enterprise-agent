"use client";
import { useEffect, useState } from "react";

import { getToken, refreshSession, signIn } from "@/lib/auth";

// Same zero-friction demo entry + token refresh as the sandbox, so /proposals is
// usable directly. Kept separate from sandbox/layout.tsx to avoid touching it.
const DEMO = { email: "demo@aria.os", password: "AriaDemo2026!" };

export default function ProposalsLayout({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (getToken()) await refreshSession().catch(() => {});
      else await signIn(DEMO.email, DEMO.password).catch(() => {});
      if (!cancelled) setReady(true);
    })();
    const id = setInterval((): void => { void refreshSession(); }, 10 * 60 * 1000);
    return () => { cancelled = true; clearInterval(id); };
  }, []);

  if (!ready) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[#0a0a0b] text-white/40 text-sm">
        …
      </div>
    );
  }
  return <>{children}</>;
}
