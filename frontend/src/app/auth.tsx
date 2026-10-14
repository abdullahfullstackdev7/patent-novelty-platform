import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { Navigate, Outlet, useLocation } from "react-router-dom";

import { api, refreshSession, setAccessToken, setSessionLostHandler } from "@/app/client";
import type { Role, TokenResponse, User } from "@/app/types";

const HINT = "priorart.session";
// A non-secret marker that a login happened in this browser, so public pages do not probe the refresh endpoint.
const readHint = () => {
  try {
    return localStorage.getItem(HINT) === "1";
  } catch {
    return false;
  }
};
const writeHint = (on: boolean) => {
  try {
    if (on) localStorage.setItem(HINT, "1");
    else localStorage.removeItem(HINT);
  } catch {
    /* storage blocked */
  }
};

type Status = "loading" | "anonymous" | "authenticated";

interface AuthContextValue {
  status: Status;
  user: User | null;
  signIn: (email: string, password: string, totp?: string) => Promise<User>;
  signOut: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function useAuth(): AuthContextValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<Status>("loading");
  const [user, setUser] = useState<User | null>(null);
  const queries = useQueryClient();

  const clear = useCallback(() => {
    setAccessToken(null);
    writeHint(false);
    setUser(null);
    setStatus("anonymous");
    queries.clear();
  }, [queries]);

  // Silent sign-in on page load: the refresh cookie is the only thing that survives a reload.
  useEffect(() => {
    let cancelled = false;
    if (!readHint()) {
      setStatus("anonymous");
      return;
    }
    refreshSession().then((session) => {
      if (cancelled) return;
      if (session) {
        setUser(session.user);
        setStatus("authenticated");
      } else {
        writeHint(false);
        setStatus("anonymous");
      }
    });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    setSessionLostHandler(clear);
    return () => setSessionLostHandler(null);
  }, [clear]);

  const signIn = useCallback<AuthContextValue["signIn"]>(async (email, password, totp) => {
    const data = await api<TokenResponse>("/auth/login", {
      method: "POST",
      body: { email, password, totp_code: totp || null },
    });
    setAccessToken(data.access_token);
    writeHint(true);
    setUser(data.user);
    setStatus("authenticated");
    return data.user;
  }, []);

  const signOut = useCallback(async () => {
    try {
      await api("/auth/logout", { method: "POST" });
    } catch {
      /* the local session is cleared either way */
    }
    clear();
  }, [clear]);

  const value = useMemo(() => ({ status, user, signIn, signOut }), [status, user, signIn, signOut]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

/** Route guard: anonymous visitors go to /login and come back afterwards. */
export function RequireAuth() {
  const { status } = useAuth();
  const location = useLocation();
  if (status === "loading") return <div role="status" aria-label="Checking your session" className="grid min-h-screen place-items-center text-stone-600">Loading...</div>;
  if (status === "anonymous") return <Navigate to="/login" replace state={{ from: location.pathname + location.search }} />;
  return <Outlet />;
}

/** Route guard by role. Other roles see a clear message, not a blank page. */
export function RequireRole({ roles }: { roles: Role[] }) {
  const { user } = useAuth();
  if (user && roles.includes(user.role)) return <Outlet />;
  return (
    <div role="alert" className="mx-auto max-w-lg py-16 text-center">
      <h1 className="text-xl">You do not have access to this page</h1>
      <p className="mt-2 text-stone-700">This area is limited to {roles.join(" and ")} accounts.</p>
    </div>
  );
}

export const canEditCases = (role: Role | undefined) => role === "admin" || role === "attorney" || role === "analyst";
