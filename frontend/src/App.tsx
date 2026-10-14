import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { Suspense, lazy } from "react";
import { Route, Routes } from "react-router-dom";

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
      <TooltipProvider>
        <AppRoutes />
      </TooltipProvider>
    </QueryClientProvider>
  );
}
