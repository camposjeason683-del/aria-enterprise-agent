"use client";
import { useEffect, useState } from "react";

import { getToken, refreshSession, signIn } from "@/lib/auth";

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
    let cancelled = false;
    (async () => {
      if (getToken()) {
        // A token from a previous session may be near/past its ~15 min expiry —
        // refresh it up front so the CopilotKit path never forwards a stale JWT.
        await refreshSession().catch(() => {});
      } else {
        await signIn(DEMO.email, DEMO.password).catch(() => {}); // degrade gracefully
      }
      if (!cancelled) setReady(true);
    })();

    // Access tokens live ~15 min and the CopilotKit runtime forwards the JWT on
    // every request; rotate it well before expiry so a long sandbox session never
    // falls to 401 (in prod, where the demo fallback is off). No-op when there is
    // no refresh token stored (e.g. demo) → degrades to the previous behavior.
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
