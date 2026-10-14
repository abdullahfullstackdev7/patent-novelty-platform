import { zodResolver } from "@hookform/resolvers/zod";
import { ShieldCheck } from "lucide-react";
import { useState } from "react";
import { useForm } from "react-hook-form";
import { Link, Navigate, useLocation, useNavigate } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { Logo } from "@/components/site/Header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { ApiError } from "@/lib/api";
import { loginSchema, type LoginInput } from "@/lib/forms";
import { Seo } from "@/lib/seo";

const inputClass = "w-full rounded-lg border border-navy-300 bg-white px-3 py-2.5 text-base text-navy aria-[invalid=true]:border-risk-high";

export default function Login() {
  const { status, signIn } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/app";
  const [needsCode, setNeedsCode] = useState(false);
  const [code, setCode] = useState("");
  const [failure, setFailure] = useState("");
  const [busy, setBusy] = useState(false);
  const [forgot, setForgot] = useState(false);
  const {
    register,
    handleSubmit,
    getValues,
    formState: { errors },
  } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });

  if (status === "authenticated") return <Navigate to={from} replace />;

  async function submit(values: LoginInput, totp?: string) {
    setBusy(true);
    setFailure("");
    try {
      await signIn(values.email, values.password, totp);
      navigate(from, { replace: true });
    } catch (error) {
      if (error instanceof ApiError && error.status === 401 && /totp code is required/i.test(error.message)) {
        setNeedsCode(true);
      } else if (error instanceof ApiError && error.status === 429) {
        setFailure("Too many attempts. Please wait a minute and try again.");
      } else if (error instanceof ApiError && error.status === 401) {
        setFailure(needsCode ? "That code was not accepted. Check the code in your authenticator app." : "The email or password is incorrect.");
      } else {
        setFailure("We could not reach the server. Check your connection and try again.");
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="grid min-h-screen lg:grid-cols-[1.1fr_1fr]">
      <Seo title="Log in" description="Sign in to PriorArt Atlas." path="/login" />
      <aside className="on-dark mesh-dark relative hidden flex-col justify-between bg-navy p-12 text-white lg:flex" aria-label="About PriorArt Atlas">
        <Logo light />
        <div className="max-w-md">
          <h2 className="text-2xl text-white">Every conclusion traces back to the source text.</h2>
          <p className="mt-4 text-lg text-navy-100">Claim charts with verbatim evidence, transparent risk rules and a review trail for every decision.</p>
          <p className="mt-8 flex items-start gap-2 text-sm text-navy-100">
            <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-teal-200" aria-hidden="true" />
            Disclosures and reports are encrypted at rest. Sign-ins and access changes are written to an audit log.
          </p>
        </div>
        <p className="text-sm text-navy-200">Decision support for qualified reviewers.</p>
      </aside>

      <main id="main" className="flex items-center justify-center bg-white px-6 py-12">
        <div className="w-full max-w-sm">
          <div className="mb-8 lg:hidden">
            <Logo />
          </div>
          <h1 className="text-xl">{needsCode ? "Two-step verification" : "Log in"}</h1>
          <p className="mt-1 text-base text-stone-700">{needsCode ? "Enter the 6-digit code from your authenticator app." : "Welcome back. Sign in to continue."}</p>

          <form
            noValidate
            aria-label="Log in"
            className="mt-6 space-y-4"
            onSubmit={handleSubmit((values) => submit(values, needsCode ? code : undefined))}
          >
            <div hidden={needsCode}>
              <label htmlFor="email" className="mb-1.5 block text-sm font-semibold">
                Email
              </label>
              <input id="email" type="email" autoComplete="username" className={inputClass} aria-invalid={errors.email ? true : undefined} aria-describedby={errors.email ? "email-error" : undefined} {...register("email")} />
              {errors.email && (
                <p id="email-error" role="alert" className="mt-1 text-sm text-risk-high">
                  {errors.email.message}
                </p>
              )}
            </div>
            <div hidden={needsCode}>
              <div className="mb-1.5 flex items-center justify-between">
                <label htmlFor="password" className="block text-sm font-semibold">
                  Password
                </label>
                <button type="button" className="text-sm font-medium text-teal-700 underline" onClick={() => setForgot(true)}>
                  Forgot password?
                </button>
              </div>
              <input id="password" type="password" autoComplete="current-password" className={inputClass} aria-invalid={errors.password ? true : undefined} aria-describedby={errors.password ? "password-error" : undefined} {...register("password")} />
              {errors.password && (
                <p id="password-error" role="alert" className="mt-1 text-sm text-risk-high">
                  {errors.password.message}
                </p>
              )}
            </div>
            {needsCode && (
              <div>
                <label htmlFor="totp" className="mb-1.5 block text-sm font-semibold">
                  Authentication code
                </label>
                <input id="totp" inputMode="numeric" autoComplete="one-time-code" maxLength={8} autoFocus value={code} onChange={(e) => setCode(e.target.value.replace(/\s/g, ""))} className={`${inputClass} font-mono tracking-widest`} />
              </div>
            )}
            {failure && (
              <p role="alert" className="text-base text-risk-high">
                {failure}
              </p>
            )}
            <Button type="submit" className="w-full" disabled={busy || (needsCode && code.length < 6)}>
              {busy ? "Signing in..." : needsCode ? "Verify and log in" : "Log in"}
            </Button>
            {needsCode && (
              <Button type="button" variant="ghost" className="w-full" onClick={() => { setNeedsCode(false); setCode(""); setFailure(""); }}>
                Use a different account
              </Button>
            )}
          </form>

          <p className="mt-8 text-sm text-stone-700">
            Need an account?{" "}
            <Link to="/contact?topic=demo" className="font-semibold text-teal-700 underline">
              Request a demo
            </Link>{" "}
            or{" "}
            <Link to="/" className="font-semibold text-teal-700 underline">
              return to the website
            </Link>
            .
          </p>
        </div>
      </main>

      <Dialog open={forgot} onOpenChange={setForgot}>
        <DialogContent>
          <DialogTitle className="text-lg font-semibold text-navy">Reset your password</DialogTitle>
          <DialogDescription className="mt-2 text-base text-stone-700">
            Password resets are issued by an administrator. Ask your administrator to generate a reset link for {getValues("email") || "your account"}; the link lets you choose a new password.
          </DialogDescription>
          <Button className="mt-6" onClick={() => setForgot(false)}>
            Got it
          </Button>
        </DialogContent>
      </Dialog>
    </div>
  );
}
