"use client";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { getToken } from "@/lib/auth";

// Home: if there's a session → the canvas; if you never logged in → /login.
// (The /sandbox route itself is directly testable — it auto-uses the demo tenant.)
export default function Home() {
  const router = useRouter();
  useEffect(() => {
    router.replace(getToken() ? "/sandbox" : "/login");
  }, [router]);
  return null;
}
