import { Bell, ChevronRight, FilePlus2, FolderOpen, LayoutDashboard, LogOut, Moon, Search, Settings, Sun, BarChart3, Menu as MenuIcon } from "lucide-react";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";

import { useAuth } from "@/app/auth";
import { OfflineBanner, ToastHost } from "@/app/components/feedback";
import { useCases } from "@/app/hooks";
import { Logo } from "@/components/site/Header";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { cn } from "@/lib/utils";

type Theme = "light" | "dark";
const THEME_KEY = "priorart.theme";

function readTheme(): Theme {
  try {
    const saved = localStorage.getItem(THEME_KEY);
    if (saved === "dark" || saved === "light") return saved;
  } catch {
    /* storage blocked */
  }
  return typeof window !== "undefined" && window.matchMedia?.("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

function useTheme() {
  const [theme, setTheme] = useState<Theme>(readTheme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
    try {
      localStorage.setItem(THEME_KEY, theme);
    } catch {
      /* ignore */
    }
    return () => document.documentElement.classList.remove("dark"); // the public site stays light
  }, [theme]);
  return [theme, () => setTheme((t) => (t === "dark" ? "light" : "dark"))] as const;
}

function useOutsideClose(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !ref.current?.contains(e.target as Node) && close();
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open, close]);
  return ref;
}

function Popover({ label, icon, badge, children }: { label: string; icon: ReactNode; badge?: number; children: (close: () => void) => ReactNode }) {
  const [open, setOpen] = useState(false);
  const ref = useOutsideClose(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <Button variant="ghost" size="sm" aria-label={label} aria-expanded={open} aria-haspopup="true" onClick={() => setOpen(!open)} className="relative">
        {icon}
        {!!badge && (
          <span className="absolute -right-0.5 -top-0.5 grid h-4 min-w-4 place-items-center rounded-full bg-risk-high px-1 text-[10px] font-semibold text-white" aria-hidden="true">
            {badge}
          </span>
        )}
      </Button>
      {open && <div className="absolute right-0 top-full z-40 mt-2 w-72 rounded-xl border border-stone-200 bg-white p-2 shadow-card">{children(() => setOpen(false))}</div>}
    </div>
  );
}

function Notifications() {
  const { user } = useAuth();
  const cases = useCases();
  const items = (cases.data?.items ?? []).filter((c) => (c.permissions.review && c.status === "in_review") || (c.owner_id === user?.id && ["changes_requested", "failed"].includes(c.status)));
  return (
    <Popover label={`Notifications${items.length ? `, ${items.length} new` : ""}`} icon={<Bell className="h-5 w-5" aria-hidden="true" />} badge={items.length}>
      {(close) =>
        items.length === 0 ? (
          <p className="p-3 text-sm text-stone-700">You are all caught up.</p>
        ) : (
          <ul>
            {items.slice(0, 6).map((c) => (
              <li key={c.id}>
                <Link to={`/app/cases/${c.id}`} onClick={close} className="block rounded-lg p-3 text-sm hover:bg-navy-50">
                  <span className="block font-semibold text-navy">{c.title}</span>
                  <span className="text-stone-700">{c.status === "in_review" ? "Waiting for your review" : c.status === "failed" ? "The run failed" : "Changes were requested"}</span>
                </Link>
              </li>
            ))}
          </ul>
        )
      }
    </Popover>
  );
}

function UserMenu() {
  const { user, signOut } = useAuth();
  const navigate = useNavigate();
  return (
    <Popover label="Account menu" icon={<span className="grid h-8 w-8 place-items-center rounded-full bg-navy text-sm font-semibold text-white">{(user?.full_name ?? "?").split(" ").map((w) => w[0]).slice(0, 2).join("")}</span>}>
      {(close) => (
        <div>
          <div className="border-b border-stone-200 p-3">
            <p className="font-semibold text-navy">{user?.full_name}</p>
            <p className="text-sm text-stone-700">{user?.email}</p>
            <p className="mt-1 text-xs font-medium uppercase tracking-wide text-teal-700">{user?.role}</p>
          </div>
          <button
            className="mt-1 flex w-full items-center gap-2 rounded-lg p-3 text-left text-sm text-navy hover:bg-navy-50"
            onClick={async () => {
              close();
              await signOut();
              navigate("/login", { replace: true });
            }}
          >
            <LogOut className="h-4 w-4" aria-hidden="true" /> Log out
          </button>
        </div>
      )}
    </Popover>
  );
}

function GlobalSearch() {
  const navigate = useNavigate();
  const [q, setQ] = useState("");
  return (
    <form
      role="search"
      className="relative hidden w-full max-w-sm md:block"
      onSubmit={(e) => {
        e.preventDefault();
        navigate(`/app/cases${q.trim() ? `?q=${encodeURIComponent(q.trim())}` : ""}`);
      }}
    >
      <label htmlFor="global-search" className="sr-only">
        Search cases
      </label>
      <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-stone-500" aria-hidden="true" />
      <input
        id="global-search"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        placeholder="Search cases by title"
        className="h-10 w-full rounded-lg border border-stone-300 bg-white pl-9 pr-3 text-sm text-navy placeholder:text-stone-500"
      />
    </form>
  );
}

const NAV_ITEMS = [
  { to: "/app", label: "Dashboard", icon: LayoutDashboard, end: true },
  { to: "/app/cases", label: "Cases", icon: FolderOpen, end: false },
  { to: "/app/cases/new", label: "New case", icon: FilePlus2, end: true, hideFor: ["viewer"] },
  { to: "/app/analytics", label: "Analytics", icon: BarChart3, end: false, adminOnly: true },
  { to: "/app/admin", label: "Admin", icon: Settings, end: false, adminOnly: true },
];

function SidebarNav({ onNavigate }: { onNavigate?: () => void }) {
  const { user } = useAuth();
  return (
    <nav aria-label="Application" className="space-y-1">
      {NAV_ITEMS.filter((i) => (!i.adminOnly || user?.role === "admin") && !i.hideFor?.includes(user?.role ?? "")).map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end && item.to !== "/app/cases"}
          onClick={onNavigate}
          className={({ isActive }) =>
            cn("flex items-center gap-3 rounded-lg px-3 py-2.5 text-base font-medium", isActive ? "bg-navy text-white" : "text-navy hover:bg-navy-50")
          }
        >
          <item.icon className="h-5 w-5" aria-hidden="true" />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

export function AppShell() {
  const [theme, toggleTheme] = useTheme();
  const [menu, setMenu] = useState(false);
  return (
    <ToastHost>
      <a href="#app-main" className="skip-link">
        Skip to main content
      </a>
      <OfflineBanner />
      <div className="flex min-h-screen bg-stone-50">
        <aside className="sticky top-0 hidden h-screen print:hidden w-60 shrink-0 flex-col border-r border-stone-200 bg-white p-4 lg:flex">
          <div className="mb-6 px-2">
            <Logo />
          </div>
          <SidebarNav />
          <p className="mt-auto px-2 text-xs text-stone-600">Decision support for qualified reviewers. Not legal advice.</p>
        </aside>
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex h-16 items-center gap-3 border-b border-stone-200 bg-white px-4">
            <Button variant="ghost" size="sm" className="lg:hidden" aria-label="Open navigation" onClick={() => setMenu(true)}>
              <MenuIcon className="h-5 w-5" aria-hidden="true" />
            </Button>
            <GlobalSearch />
            <div className="ml-auto flex items-center gap-1">
              <Button variant="ghost" size="sm" aria-label={theme === "dark" ? "Switch to light theme" : "Switch to dark theme"} onClick={toggleTheme}>
                {theme === "dark" ? <Sun className="h-5 w-5" aria-hidden="true" /> : <Moon className="h-5 w-5" aria-hidden="true" />}
              </Button>
              <Notifications />
              <UserMenu />
            </div>
          </header>
          <main id="app-main" tabIndex={-1} className="mx-auto w-full max-w-[1400px] flex-1 p-4 outline-none md:p-8">
            <Outlet />
          </main>
        </div>
      </div>
      <Dialog open={menu} onOpenChange={setMenu}>
        <DialogContent side="right">
          <DialogTitle className="mb-4 text-lg font-semibold text-navy">Navigation</DialogTitle>
          <DialogDescription className="sr-only">Application sections</DialogDescription>
          <SidebarNav onNavigate={() => setMenu(false)} />
        </DialogContent>
      </Dialog>
    </ToastHost>
  );
}

export function PageHeader({ crumbs, title, actions, subtitle }: { crumbs: { label: string; to?: string }[]; title: string; actions?: ReactNode; subtitle?: ReactNode }) {
  return (
    <div className="mb-6">
      <nav aria-label="Breadcrumb">
        <ol className="flex flex-wrap items-center gap-1 text-sm text-stone-700">
          {crumbs.map((c, i) => (
            <li key={c.label} className="flex items-center gap-1">
              {i > 0 && <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />}
              {c.to && i < crumbs.length - 1 ? (
                <Link to={c.to} className="hover:text-teal-700 hover:underline">
                  {c.label}
                </Link>
              ) : (
                <span aria-current={i === crumbs.length - 1 ? "page" : undefined}>{c.label}</span>
              )}
            </li>
          ))}
        </ol>
      </nav>
      <div className="mt-2 flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-xl md:text-2xl">{title}</h1>
          {subtitle && <div className="mt-1 text-base text-stone-700">{subtitle}</div>}
        </div>
        {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
      </div>
    </div>
  );
}
