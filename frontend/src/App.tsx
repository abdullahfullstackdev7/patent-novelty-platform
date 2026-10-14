import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

import { AuthProvider, RequireAuth, RequireRole } from "@/app/auth";
import { Layout } from "@/components/site/Layout";
import { TooltipProvider } from "@/components/ui/overlay";
import Home from "@/pages/Home";
import NotFound from "@/pages/NotFound";

// Everything except Home is split out, so the first page stays small.
const Platform = lazy(() => import("@/pages/Platform"));
const Solutions = lazy(() => import("@/pages/Solutions"));
const Pricing = lazy(() => import("@/pages/Pricing"));
const Contact = lazy(() => import("@/pages/Contact"));
const Legal = lazy(() => import("@/pages/Legal"));
const Login = lazy(() => import("@/pages/Login"));
const AppShell = lazy(() => import("@/app/components/Shell").then((m) => ({ default: m.AppShell })));
const Dashboard = lazy(() => import("@/app/pages/Dashboard"));
const NewCase = lazy(() => import("@/app/pages/NewCase"));
const CaseWorkspace = lazy(() => import("@/app/pages/CaseWorkspace"));
const RunProgress = lazy(() => import("@/app/pages/RunProgress"));
const Admin = lazy(() => import("@/app/pages/Admin"));
const AcceptLink = lazy(() => import("@/app/pages/Misc").then((m) => ({ default: m.AcceptLink })));
const AnalyticsPage = lazy(() => import("@/analytics/AnalyticsPage"));
const AppNotFound = lazy(() => import("@/app/pages/Misc").then((m) => ({ default: m.AppNotFound })));
const Security = lazy(() => import("@/pages/Info").then((m) => ({ default: m.Security })));
const About = lazy(() => import("@/pages/Info").then((m) => ({ default: m.About })));
const Resources = lazy(() => import("@/pages/Info").then((m) => ({ default: m.Resources })));
const ResourceArticle = lazy(() => import("@/pages/Info").then((m) => ({ default: m.ResourceArticle })));

export const makeQueryClient = () => new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

export function AppRoutes() {
  return (
    <Suspense fallback={<div className="min-h-[60vh]" role="status" aria-label="Loading page" />}>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/accept" element={<AcceptLink />} />
        <Route path="/app" element={<RequireAuth />}>
          <Route element={<AppShell />}>
            <Route index element={<Dashboard />} />
            <Route path="cases" element={<Dashboard listOnly />} />
            <Route path="cases/new" element={<NewCase />} />
            <Route path="cases/:caseId" element={<CaseWorkspace />} />
            <Route path="cases/:caseId/run" element={<RunProgress />} />
            <Route element={<RequireRole roles={["admin"]} />}>
              <Route path="analytics" element={<AnalyticsPage />} />
              <Route path="admin" element={<Admin />} />
            </Route>
            <Route path="*" element={<AppNotFound />} />
          </Route>
        </Route>
        <Route element={<Layout />}>
          <Route index element={<Home />} />
          <Route path="platform" element={<Platform />} />
          <Route path="solutions" element={<Solutions />} />
          <Route path="pricing" element={<Pricing />} />
          <Route path="security" element={<Security />} />
          <Route path="about" element={<About />} />
          <Route path="contact" element={<Contact />} />
          <Route path="resources" element={<Resources />} />
          <Route path="resources/:slug" element={<ResourceArticle />} />
          <Route path="legal/:doc" element={<Legal />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}

export default function App({ client = makeQueryClient() }: { client?: QueryClient }) {
  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <TooltipProvider>
          <AppRoutes />
        </TooltipProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
