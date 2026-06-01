import { redirect } from "next/navigation";

// Home → the app dashboard (which gates on auth and bounces to /login if needed).
export default function Home() {
  redirect("/app");
}
