import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Copy, KeyRound, UserPlus } from "lucide-react";
import { useState } from "react";

import { useAuth } from "@/app/auth";
import { api } from "@/app/client";
import { EmptyState, ErrorState, Loading, messageOf, useToast } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { useAudit, useCorpus, useLlmSettings, useLlmStatus, useUsers } from "@/app/hooks";
import type { InviteResult, LlmMode, ProviderStatus, Role, User } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/overlay";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Seo } from "@/lib/seo";

const ROLES: Role[] = ["admin", "attorney", "analyst", "viewer"];
const field = "h-10 w-full rounded-lg border border-stone-300 bg-white px-3 text-sm text-navy";

// ---- users ------------------------------------------------------------------------------------------------------

function Users() {
  const { user: me } = useAuth();
  const users = useUsers();
  const qc = useQueryClient();
  const toast = useToast();
  const [invite, setInvite] = useState(false);
  const [link, setLink] = useState<{ title: string; token: string; expires: string } | null>(null);
  const [form, setForm] = useState({ email: "", full_name: "", role: "analyst" as Role });
  const refresh = () => qc.invalidateQueries({ queryKey: ["users"] });

  const patch = useMutation({
    mutationFn: (v: { id: string; body: Partial<Pick<User, "role" | "is_active">> }) => api<User>(`/users/${v.id}`, { method: "PATCH", body: v.body }),
    onSuccess: () => { toast.success("User updated"); refresh(); },
    onError: (e) => toast.error("Could not update the user", messageOf(e)),
  });
  const create = useMutation({
    mutationFn: () => api<InviteResult>("/users/invite", { method: "POST", body: form }),
    onSuccess: (r) => {
      setInvite(false);
      setForm({ email: "", full_name: "", role: "analyst" });
      setLink({ title: `Invitation for ${r.user.full_name}`, token: r.invite_token, expires: r.expires_at });
      refresh();
    },
    onError: (e) => toast.error("Could not send the invitation", messageOf(e)),
  });
  const reset = useMutation({
    mutationFn: (u: User) => api<{ reset_token: string; expires_at: string }>(`/users/${u.id}/reset-password`, { method: "POST" }).then((r) => ({ r, u })),
    onSuccess: ({ r, u }) => setLink({ title: `Password reset for ${u.full_name}`, token: r.reset_token, expires: r.expires_at }),
    onError: (e) => toast.error("Could not reset the password", messageOf(e)),
  });

  if (users.isLoading) return <Loading rows={4} />;
  if (users.isError) return <ErrorState error={users.error} onRetry={() => users.refetch()} />;
  const url = link ? `${window.location.origin}/accept?token=${encodeURIComponent(link.token)}` : "";

  return (
    <div className="space-y-4">
      <div className="flex justify-end"><Button onClick={() => setInvite(true)}><UserPlus className="h-4 w-4" aria-hidden="true" /> Invite user</Button></div>
      <Card>
        <CardContent className="p-0">
          <Table>
            <caption className="sr-only">Users</caption>
            <TableHead>
              <TableRow>
                <TableHeader scope="col">Name</TableHeader>
                <TableHeader scope="col">Role</TableHeader>
                <TableHeader scope="col">Status</TableHeader>
                <TableHeader scope="col">Last sign-in</TableHeader>
                <TableHeader scope="col"><span className="sr-only">Actions</span></TableHeader>
              </TableRow>
            </TableHead>
            <TableBody>
              {(users.data ?? []).map((u) => (
                <TableRow key={u.id}>
                  <TableCell><span className="font-semibold text-navy">{u.full_name}</span><br /><span className="text-sm">{u.email}</span></TableCell>
                  <TableCell>
                    <label className="sr-only" htmlFor={`role-${u.id}`}>Role for {u.full_name}</label>
                    <select id={`role-${u.id}`} className={`${field} w-32`} value={u.role} disabled={u.id === me?.id || patch.isPending} onChange={(e) => patch.mutate({ id: u.id, body: { role: e.target.value as Role } })}>
                      {ROLES.map((r) => <option key={r} value={r}>{r}</option>)}
                    </select>
                  </TableCell>
                  <TableCell>{u.is_active ? <Badge tone="low">Active</Badge> : <Badge>Deactivated</Badge>}{u.totp_enabled && <Badge tone="teal" className="ml-1">2FA</Badge>}</TableCell>
                  <TableCell>{u.last_login_at ? new Date(u.last_login_at).toLocaleString() : "Never"}</TableCell>
                  <TableCell>
                    <div className="flex gap-1">
                      <Button variant="ghost" size="sm" disabled={u.id === me?.id} onClick={() => patch.mutate({ id: u.id, body: { is_active: !u.is_active } })}>{u.is_active ? "Deactivate" : "Activate"}</Button>
                      <Button variant="ghost" size="sm" aria-label={`Reset password for ${u.full_name}`} disabled={u.id === me?.id} onClick={() => reset.mutate(u)}><KeyRound className="h-4 w-4" aria-hidden="true" /></Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>

      <Dialog open={invite} onOpenChange={setInvite}>
        <DialogContent>
          <DialogTitle className="text-lg font-semibold text-navy">Invite a user</DialogTitle>
          <DialogDescription className="sr-only">Create an invitation link</DialogDescription>
          <form className="mt-4 space-y-3" onSubmit={(e) => { e.preventDefault(); create.mutate(); }}>
            <div><label htmlFor="inv-name" className="mb-1 block text-sm font-semibold">Full name</label><input id="inv-name" required className={field} value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} /></div>
            <div><label htmlFor="inv-email" className="mb-1 block text-sm font-semibold">Email</label><input id="inv-email" type="email" required className={field} value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
            <div><label htmlFor="inv-role" className="mb-1 block text-sm font-semibold">Role</label><select id="inv-role" className={field} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r} value={r}>{r}</option>)}</select></div>
            <div className="flex justify-end gap-2 pt-2"><Button type="button" variant="outline" onClick={() => setInvite(false)}>Cancel</Button><Button type="submit" disabled={create.isPending}>Create invitation</Button></div>
          </form>
        </DialogContent>
      </Dialog>

      <Dialog open={!!link} onOpenChange={(o) => !o && setLink(null)}>
        <DialogContent>
          {link && (
            <>
              <DialogTitle className="text-lg font-semibold text-navy">{link.title}</DialogTitle>
              <DialogDescription className="mt-2 text-base text-stone-700">Send this one-time link to the person. It is shown only now and expires {new Date(link.expires).toLocaleString()}.</DialogDescription>
              <label htmlFor="link" className="sr-only">One-time link</label>
              <input id="link" readOnly value={url} className={`${field} mt-3 font-mono`} onFocus={(e) => e.currentTarget.select()} />
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="outline" onClick={async () => { await navigator.clipboard?.writeText(url); toast.success("Link copied"); }}><Copy className="h-4 w-4" aria-hidden="true" /> Copy</Button>
                <Button onClick={() => setLink(null)}>Done</Button>
              </div>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}

// ---- LLM -----------------------------------------------------------------------------------------------------------

function Meter({ label, used, limit, percent }: { label: string; used: number; limit: number; percent?: number }) {
  const pct = Math.min(100, percent ?? (limit ? (used / limit) * 100 : 0));
  return (
    <div>
      <div className="flex justify-between text-sm"><span>{label}</span><span className="font-mono">{used.toLocaleString()} / {limit.toLocaleString()}</span></div>
      <div className="mt-1 h-2 rounded-full bg-stone-200" role="meter" aria-label={label} aria-valuemin={0} aria-valuemax={100} aria-valuenow={Math.round(pct)}>
        <div className={`h-2 rounded-full ${pct > 85 ? "bg-risk-high" : pct > 60 ? "bg-risk-medium" : "bg-teal-600"}`} style={{ width: `${pct}%` }} />
      </div>
    </div>
  );
}

function ProviderCard({ p }: { p: ProviderStatus }) {
  return (
    <Card>
      <CardContent className="space-y-3">
        <div className="flex items-center justify-between"><h3 className="text-base capitalize">{p.name}</h3><Badge tone={p.configured ? "low" : "neutral"}>{p.configured ? "Configured" : "No API key"}</Badge></div>
        <p className="font-mono text-xs text-stone-700">{p.model}</p>
        <Meter label="Tokens today" used={p.day.tokens_used} limit={p.day.tokens_limit} percent={p.day.tokens_percent} />
        <Meter label="Requests today" used={p.day.requests_used} limit={p.day.requests_limit} percent={p.day.requests_percent} />
        <Meter label="Tokens this minute" used={p.minute.tokens_used} limit={p.minute.tokens_limit} />
        <p className="text-sm">Circuit breaker: <Badge tone={p.breaker.state === "closed" ? "low" : "high"}>{p.breaker.state}</Badge></p>
      </CardContent>
    </Card>
  );
}

function Llm() {
  const status = useLlmStatus();
  const settings = useLlmSettings();
  const qc = useQueryClient();
  const toast = useToast();
  const [draft, setDraft] = useState<{ mode: LlmMode; groq_model: string; gemini_model: string } | null>(null);
  const form = draft ?? (settings.data ? { mode: settings.data.mode, groq_model: settings.data.groq_model, gemini_model: settings.data.gemini_model } : null);

  const save = useMutation({
    mutationFn: () => api("/admin/llm/settings", { method: "PUT", body: form }),
    onSuccess: () => { toast.success("LLM settings saved"); setDraft(null); qc.invalidateQueries({ queryKey: ["llm-settings"] }); qc.invalidateQueries({ queryKey: ["llm-status"] }); qc.invalidateQueries({ queryKey: ["llm-mode"] }); },
    onError: (e) => toast.error("Could not save the settings", messageOf(e)),
  });
  const resetBreakers = useMutation({
    mutationFn: () => api("/admin/llm/breakers/reset", { method: "POST" }),
    onSuccess: () => { toast.success("Circuit breakers reset"); qc.invalidateQueries({ queryKey: ["llm-status"] }); },
    onError: (e) => toast.error("Could not reset the breakers", messageOf(e)),
  });

  if (settings.isLoading || status.isLoading) return <Loading rows={4} />;
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => settings.refetch()} />;
  return (
    <div className="space-y-6">
      {form && (
        <Card>
          <CardContent>
            <h2 className="text-lg">Settings</h2>
            <form className="mt-3 grid gap-4 sm:grid-cols-3" onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
              <div><label htmlFor="llm-mode" className="mb-1 block text-sm font-semibold">Mode</label>
                <select id="llm-mode" className={field} value={form.mode} onChange={(e) => setDraft({ ...form, mode: e.target.value as LlmMode })}>
                  <option value="auto">Automatic</option><option value="groq">Groq only</option><option value="gemini">Gemini only</option><option value="local_only">Local only</option>
                </select></div>
              <div><label htmlFor="llm-groq" className="mb-1 block text-sm font-semibold">Groq model</label><input id="llm-groq" className={`${field} font-mono`} value={form.groq_model} onChange={(e) => setDraft({ ...form, groq_model: e.target.value })} /></div>
              <div><label htmlFor="llm-gemini" className="mb-1 block text-sm font-semibold">Gemini model</label><input id="llm-gemini" className={`${field} font-mono`} value={form.gemini_model} onChange={(e) => setDraft({ ...form, gemini_model: e.target.value })} /></div>
              <div className="flex gap-2 sm:col-span-3"><Button type="submit" disabled={!draft || save.isPending}>Save settings</Button><Button type="button" variant="outline" disabled={resetBreakers.isPending} onClick={() => resetBreakers.mutate()}>Reset circuit breakers</Button></div>
            </form>
          </CardContent>
        </Card>
      )}
      <div className="grid gap-4 md:grid-cols-2">{(status.data?.providers ?? []).map((p) => <ProviderCard key={p.name} p={p} />)}</div>
    </div>
  );
}

// ---- corpus and audit ------------------------------------------------------------------------------------------------

const SOURCE_LABEL: Record<string, string> = { PV_GRANT: "PatentsView granted patents", HUPD_APP: "HUPD applications" };

function Corpus() {
  const corpus = useCorpus();
  if (corpus.isLoading) return <Loading rows={2} />;
  if (corpus.isError) return <ErrorState error={corpus.error} onRetry={() => corpus.refetch()} />;
  const d = corpus.data!;
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <Card><CardContent><p className="text-sm text-stone-700">Patent documents</p><p className="text-2xl font-semibold text-navy">{d.patents.toLocaleString()}</p></CardContent></Card>
      <Card><CardContent><p className="text-sm text-stone-700">Searchable passages</p><p className="text-2xl font-semibold text-navy">{d.chunks.toLocaleString()}</p></CardContent></Card>
      <Card><CardContent><p className="text-sm text-stone-700">Sources loaded</p><ul className="mt-1 text-base text-navy">{d.sources.length ? d.sources.map((s) => <li key={s}>{SOURCE_LABEL[s] ?? s}</li>) : <li>None</li>}</ul></CardContent></Card>
    </div>
  );
}

const PAGE = 25;
function Audit() {
  const [page, setPage] = useState(0);
  const [action, setAction] = useState("");
  const audit = useAudit({ action: action || undefined, limit: PAGE, offset: page * PAGE });
  return (
    <div className="space-y-3">
      <div className="max-w-xs"><label htmlFor="audit-action" className="mb-1 block text-sm font-semibold">Filter by action</label><input id="audit-action" className={field} placeholder="for example auth.login" value={action} onChange={(e) => { setAction(e.target.value.trim()); setPage(0); }} /></div>
      {audit.isLoading ? <Loading rows={5} /> : audit.isError ? <ErrorState error={audit.error} onRetry={() => audit.refetch()} /> : (audit.data ?? []).length === 0 ? <EmptyState title="No audit entries" text="Nothing matches this filter." /> : (
        <Card><CardContent className="p-0">
          <Table>
            <caption className="sr-only">Audit log</caption>
            <TableHead><TableRow><TableHeader scope="col">When</TableHeader><TableHeader scope="col">Action</TableHeader><TableHeader scope="col">Entity</TableHeader><TableHeader scope="col">IP</TableHeader></TableRow></TableHead>
            <TableBody>
              {audit.data!.map((a) => (
                <TableRow key={a.id}>
                  <TableCell><time dateTime={a.created_at}>{new Date(a.created_at).toLocaleString()}</time></TableCell>
                  <TableCell className="font-mono text-sm">{a.action}</TableCell>
                  <TableCell>{a.entity_type ? `${a.entity_type} ${a.entity_id?.slice(0, 8) ?? ""}` : ""}</TableCell>
                  <TableCell className="font-mono text-sm">{a.ip_address}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent></Card>
      )}
      <div className="flex items-center gap-2"><Button variant="outline" size="sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Newer</Button><Button variant="outline" size="sm" disabled={(audit.data?.length ?? 0) < PAGE} onClick={() => setPage(page + 1)}>Older</Button><span className="text-sm text-stone-700">Page {page + 1}</span></div>
    </div>
  );
}

export default function Admin() {
  return (
    <>
      <Seo title="Admin" description="Users, language models, corpus and audit log." path="/app/admin" />
      <PageHeader crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Admin" }]} title="Administration" />
      <Tabs defaultValue="users">
        <TabsList aria-label="Admin sections">
          <TabsTrigger value="users">Users and roles</TabsTrigger>
          <TabsTrigger value="llm">Language models</TabsTrigger>
          <TabsTrigger value="corpus">Corpus</TabsTrigger>
          <TabsTrigger value="audit">Audit log</TabsTrigger>
        </TabsList>
        <TabsContent value="users"><Users /></TabsContent>
        <TabsContent value="llm"><Llm /></TabsContent>
        <TabsContent value="corpus"><Corpus /></TabsContent>
        <TabsContent value="audit"><Audit /></TabsContent>
      </Tabs>
    </>
  );
}
