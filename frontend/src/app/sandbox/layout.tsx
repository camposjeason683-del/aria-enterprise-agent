"use client";
import { useEffect, useState } from "react";

import { getToken, signIn } from "@/lib/auth";

// Demo tenant — lets anyone test the sandbox directly with zero friction.
const DEMO = { email: "demo@aria.os", password: "AriaDemo2026!" };

/**
 * Zero-friction entry for the original /sandbox canvas: if there's no session,
 * silently sign in as the demo tenant (no login wall) so the multi-tenant
 * backend still gets a tenant JWT. Wraps the canvas WITHOUT touching
 * sandbox/page.tsx. A real login is available at /login.
 */
export default function SandboxLayout({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (getToken()) {
      setReady(true);
      return;
    }
    signIn(DEMO.email, DEMO.password)
      .catch(() => {}) // even if it fails, render the canvas (degrades gracefully)
      .finally(() => setReady(true));
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
