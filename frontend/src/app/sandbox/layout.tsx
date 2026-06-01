"use client";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { getToken } from "@/lib/auth";

/**
 * Auth gate for the original /sandbox canvas — redirects to /login when there is
 * no session, so the multi-tenant backend always gets a tenant JWT. This wraps
 * the canvas WITHOUT modifying sandbox/page.tsx.
 */
export default function SandboxLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!getToken()) router.replace("/login");
    else setReady(true);
  }, [router]);

  if (!ready) {
    return (
      <div className="flex h-screen w-screen items-center justify-center bg-[#0a0a0b] text-white/40 text-sm">
        …
      </div>
    );
  }
  return <>{children}</>;
}
