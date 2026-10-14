import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { Link } from "react-router-dom";

import { Logo } from "@/components/site/Header";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, login } from "@/lib/api";
import { loginSchema, type LoginInput } from "@/lib/forms";
import { Seo } from "@/lib/seo";

const inputClass = "w-full rounded-lg border border-navy-300 bg-white px-3 py-2.5 text-base text-navy aria-[invalid=true]:border-risk-high";

/** The sign-in form talks to the real auth API. The application shell it leads to arrives in Phase 8. */
export default function Login() {
  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginInput>({ resolver: zodResolver(loginSchema) });
  const signIn = useMutation({ mutationFn: login });

  return (
    <main id="main" className="mesh flex min-h-screen items-center justify-center px-4 py-12">
      <Seo title="Log in" description="Sign in to PriorArt Atlas." path="/login" />
      <div className="w-full max-w-md">
        <div className="mb-6 flex justify-center">
          <Logo />
        </div>
        <Card>
          <CardContent>
            <h1 className="text-xl">Log in</h1>
            {signIn.isSuccess ? (
              <p role="status" className="mt-4 text-base text-stone-700">
                You are signed in. The workspace opens here in the next release of the application.
              </p>
            ) : (
              <form onSubmit={handleSubmit((v) => signIn.mutate(v))} noValidate className="mt-5 space-y-4" aria-label="Log in">
                <div>
                  <label htmlFor="email" className="mb-1.5 block text-sm font-semibold">
                    Email
                  </label>
                  <input
                    id="email"
                    type="email"
                    autoComplete="username"
                    className={inputClass}
                    aria-invalid={errors.email ? true : undefined}
                    aria-describedby={errors.email ? "email-error" : undefined}
                    {...register("email")}
                  />
                  {errors.email && (
                    <p id="email-error" role="alert" className="mt-1 text-sm text-risk-high">
                      {errors.email.message}
                    </p>
                  )}
                </div>
                <div>
                  <label htmlFor="password" className="mb-1.5 block text-sm font-semibold">
                    Password
                  </label>
                  <input
                    id="password"
                    type="password"
                    autoComplete="current-password"
                    className={inputClass}
                    aria-invalid={errors.password ? true : undefined}
                    aria-describedby={errors.password ? "password-error" : undefined}
                    {...register("password")}
                  />
                  {errors.password && (
                    <p id="password-error" role="alert" className="mt-1 text-sm text-risk-high">
                      {errors.password.message}
                    </p>
                  )}
                </div>
                {signIn.isError && (
                  <p role="alert" className="text-base text-risk-high">
                    {signIn.error instanceof ApiError && signIn.error.status === 429
                      ? "Too many attempts. Please wait a minute and try again."
                      : "The email or password is incorrect."}
                  </p>
                )}
                <Button type="submit" className="w-full" disabled={signIn.isPending}>
                  {signIn.isPending ? "Signing in..." : "Log in"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
        <p className="mt-6 text-center text-sm text-stone-700">
          No account yet?{" "}
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
  );
}
