import { redirect } from "next/navigation";

// Home → the original /sandbox canvas (the main interface). It gates on auth
// (sandbox/layout.tsx) and bounces to /login if there's no session.
export default function Home() {
  redirect("/sandbox");
}
