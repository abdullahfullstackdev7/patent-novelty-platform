import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";

import { api } from "@/app/client";
import { EmptyState } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { Logo } from "@/components/site/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError } from "@/lib/api";
import { Seo } from "@/lib/seo";

/** Set a password from an invitation or an administrator reset link. */
export function AcceptLink() {
  const [params] = useSearchParams();
  const token = params.get("token") ?? "";
  const navigate = useNavigate();
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await api("/auth/accept-invite", { method: "POST", body: { token, password, full_name: name.trim() || null } });
      navigate("/login", { replace: true });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "We could not reach the server.");
    } finally {
      setBusy(false);
    }
  }

  const input = "w-full rounded-lg border border-navy-300 bg-white px-3 py-2.5 text-base text-navy";
  return (
    <main id="main" className="mesh grid min-h-screen place-items-center px-4 py-12">
      <Seo title="Set your password" description="Choose a password for your account." path="/accept" />
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center"><Logo /></div>
        <Card><CardContent>
          <h1 className="text-xl">Set your password</h1>
          {token.length < 20 ? (
            <p role="alert" className="mt-3 text-risk-high">This link is incomplete. Ask your administrator for a new one.</p>
          ) : (
            <form className="mt-4 space-y-4" onSubmit={submit} aria-label="Set password">
              <div><label htmlFor="n" className="mb-1.5 block text-sm font-semibold">Your name (optional)</label><input id="n" className={input} value={name} onChange={(e) => setName(e.target.value)} autoComplete="name" /></div>
              <div><label htmlFor="p" className="mb-1.5 block text-sm font-semibold">New password</label><input id="p" type="password" required className={input} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="new-password" /></div>
              {error && <p role="alert" className="text-risk-high">{error}</p>}
              <Button type="submit" className="w-full" disabled={busy || !password}>Set password</Button>
            </form>
          )}
          <p className="mt-6 text-sm"><Link to="/login" className="font-semibold text-teal-700 underline">Back to log in</Link></p>
        </CardContent></Card>
      </div>
    </main>
  );
}

export function AppNotFound() {
  return (
    <>
      <PageHeader crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Not found" }]} title="Page not found" />
      <EmptyState title="We could not find that page" text="Check the address, or return to the dashboard." action={<Button asChild><Link to="/app">Go to the dashboard</Link></Button>} />
    </>
  );
}
