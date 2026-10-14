import { useMutation } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, GitMerge, Plus, Scissors, Sparkles, Trash2, Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";

import { api } from "@/app/client";
import { Loading, messageOf, useToast } from "@/app/components/feedback";
import { PageHeader } from "@/app/components/Shell";
import { useDisclosure, useLlmMode } from "@/app/hooks";
import { mergeWithNext, moveItem, splitElement, validateDisclosure, type DraftElement } from "@/app/logic";
import type { CaseItem, Disclosure, ExtractResult, Job, LlmMode } from "@/app/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Seo } from "@/lib/seo";
import { cn } from "@/lib/utils";

const STEPS = ["Disclosure", "Elements", "Search settings", "Review and run"];
const DRAFT_KEY = "priorart.newcase.draft";
const MODES: { value: LlmMode; label: string }[] = [
  { value: "auto", label: "Automatic (Groq, then Gemini, then local)" },
  { value: "groq", label: "Groq only" },
  { value: "gemini", label: "Gemini only" },
  { value: "local_only", label: "Local only (nothing leaves this server)" },
];

interface Fields {
  title: string;
  technical_field: string;
  problem: string;
  solution: string;
}
const EMPTY: Fields = { title: "", technical_field: "", problem: "", solution: "" };
const uid = () => Math.random().toString(36).slice(2, 10);
const input = "w-full rounded-lg border border-stone-300 bg-white px-3 py-2.5 text-base text-navy aria-[invalid=true]:border-risk-high";

function readDraft(): Fields {
  try {
    return { ...EMPTY, ...JSON.parse(localStorage.getItem(DRAFT_KEY) ?? "{}") };
  } catch {
    return EMPTY;
  }
}

function Field({ id, label, error, hint, children }: { id: string; label: string; error?: string; hint?: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-semibold">{label}</label>
      {children}
      {hint && !error && <p className="mt-1 text-sm text-stone-600">{hint}</p>}
      {error && <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-risk-high">{error}</p>}
    </div>
  );
}

export default function NewCase() {
  const navigate = useNavigate();
  const toast = useToast();
  const [params] = useSearchParams();
  const resumeId = params.get("case");
  const resumed = useDisclosure(resumeId ?? "");
  const mode = useLlmMode();

  const [step, setStep] = useState(0);
  const [caseId, setCaseId] = useState<string | null>(resumeId);
  const [fields, setFields] = useState<Fields>(() => (resumeId ? EMPTY : readDraft()));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [elements, setElements] = useState<DraftElement[]>([]);
  const [priorityDate, setPriorityDate] = useState("");
  const [references, setReferences] = useState(3);
  const [llmMode, setLlmMode] = useState<LlmMode>("auto");
  const [saved, setSaved] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const cursors = useRef<Record<string, number>>({});
  const loaded = useRef(false);

  // Resume a draft case: load its disclosure once.
  useEffect(() => {
    if (!resumeId || loaded.current || !resumed.data) return;
    loaded.current = true;
    const d: Disclosure = resumed.data;
    setFields({ title: d.title, technical_field: d.technical_field, problem: d.problem, solution: d.solution });
    setElements(d.elements.map((e) => ({ uid: e.id, text: e.text, source: (e.source as DraftElement["source"]) ?? "user" })));
  }, [resumeId, resumed.data]);

  // Before a case exists the draft lives in this browser only. Afterwards it is saved to the server.
  useEffect(() => {
    if (caseId) return;
    try {
      localStorage.setItem(DRAFT_KEY, JSON.stringify(fields));
    } catch {
      /* storage blocked */
    }
  }, [fields, caseId]);

  const payload = () => ({ ...fields, elements: elements.filter((e) => e.text.trim()).map((e) => ({ text: e.text.trim(), source: e.source })) });

  const saveDisclosure = useMutation({
    mutationFn: (id: string) => api<Disclosure>(`/cases/${id}/disclosure`, { method: "PUT", body: payload() }),
  });

  // Autosave after a pause once the case exists.
  const first = useRef(true);
  useEffect(() => {
    if (!caseId || step > 1) return;
    if (first.current) {
      first.current = false;
      return;
    }
    setSaved("saving");
    const timer = setTimeout(() => {
      saveDisclosure.mutate(caseId, { onSuccess: () => setSaved("saved"), onError: () => setSaved("error") });
    }, 1200);
    return () => clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fields, elements, caseId]);

  const create = useMutation({
    mutationFn: async () => {
      const id = caseId ?? (await api<CaseItem>("/cases", { method: "POST", body: { title: fields.title.trim() } })).id;
      await api(`/cases/${id}/disclosure`, { method: "PUT", body: payload() });
      return id;
    },
    onSuccess: (id) => {
      setCaseId(id);
      try {
        localStorage.removeItem(DRAFT_KEY);
      } catch {
        /* ignore */
      }
      setStep(1);
    },
    onError: (e) => toast.error("Could not save the disclosure", messageOf(e)),
  });

  const extract = useMutation({
    mutationFn: async () => {
      await api(`/cases/${caseId}/disclosure`, { method: "PUT", body: payload() });
      return api<ExtractResult>(`/cases/${caseId}/disclosure/extract-elements`, { method: "POST" });
    },
    onSuccess: (r) => {
      setElements(r.elements.map((e) => ({ uid: uid(), text: e.text, source: (e.source as DraftElement["source"]) ?? "llm" })));
      toast.success(`${r.elements.length} elements extracted`, r.fallback_reason ? `Used local extraction: ${r.fallback_reason}` : r.cache_hit ? "Served from cache" : undefined);
    },
    onError: (e) => toast.error("Extraction failed", messageOf(e)),
  });

  const upload = useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return api<{ filename: string; characters: number; text: string }>("/disclosure/parse-upload", { method: "POST", form });
    },
    onSuccess: (r) => {
      setFields((f) => ({ ...f, solution: f.solution ? `${f.solution}\n\n${r.text}` : r.text, title: f.title || r.filename.replace(/\.[^.]+$/, "") }));
      toast.success(`Loaded ${r.filename}`, `${r.characters.toLocaleString()} characters added to the solution`);
    },
    onError: (e) => toast.error("Could not read the file", messageOf(e)),
  });

  const run = useMutation({
    mutationFn: async () => {
      await api(`/cases/${caseId}`, { method: "PATCH", body: { priority_date: priorityDate || null, llm_mode: llmMode } });
      await api(`/cases/${caseId}/disclosure`, { method: "PUT", body: payload() });
      return api<Job>(`/cases/${caseId}/run`, { method: "POST", body: { references, force_search: false } });
    },
    onSuccess: () => navigate(`/app/cases/${caseId}/run`),
    onError: (e) => toast.error("Could not start the run", messageOf(e)),
  });

  function next() {
    if (step === 0) {
      const found = validateDisclosure(fields);
      setErrors(found);
      if (Object.keys(found).length) return;
      create.mutate();
    } else if (step === 1) {
      if (!elements.some((e) => e.text.trim())) {
        toast.error("Add at least one element", "Extract elements or type them in.");
        return;
      }
      setStep(2);
    } else setStep(step + 1);
  }

  const setEl = (i: number, patch: Partial<DraftElement>) => setElements((l) => l.map((e, j) => (j === i ? { ...e, ...patch, source: "user" } : e)));
  const filled = elements.filter((e) => e.text.trim()).length;

  if (resumeId && resumed.isLoading) return <Loading label="Loading your draft" />;

  return (
    <>
      <Seo title="New case" description="Create a novelty case." path="/app/cases/new" />
      <PageHeader crumbs={[{ label: "Dashboard", to: "/app" }, { label: "Cases", to: "/app/cases" }, { label: "New case" }]} title="New case" />

      <ol className="mb-6 flex flex-wrap gap-2" aria-label="Progress">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined} className={cn("flex items-center gap-2 rounded-full px-3 py-1.5 text-sm font-medium", i === step ? "bg-navy text-white" : i < step ? "bg-teal-50 text-teal-800" : "bg-stone-100 text-stone-700")}>
            <span className="font-semibold">{i + 1}</span> {s}
          </li>
        ))}
      </ol>

      <Card>
        <CardContent className="space-y-5">
          {step === 0 && (
            <>
              <div role="note" className="rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900">
                <strong>Confidentiality.</strong> Disclosures are encrypted at rest and visible only to people you share the case with.
                {mode.data && (
                  <> Text processing mode: <strong>{MODES.find((m) => m.value === mode.data.mode)?.label ?? mode.data.mode}</strong>{mode.data.llm_available ? "" : " (no cloud model is configured, so analysis stays local)"}.</>
                )}
              </div>
              <Field id="title" label="Title" error={errors.title}>
                <input id="title" className={input} value={fields.title} aria-invalid={errors.title ? true : undefined} aria-describedby={errors.title ? "title-error" : undefined} onChange={(e) => setFields({ ...fields, title: e.target.value })} />
              </Field>
              <Field id="technical_field" label="Technical field (optional)">
                <input id="technical_field" className={input} value={fields.technical_field} onChange={(e) => setFields({ ...fields, technical_field: e.target.value })} />
              </Field>
              <Field id="problem" label="Problem addressed" error={errors.problem}>
                <textarea id="problem" rows={4} className={input} value={fields.problem} aria-invalid={errors.problem ? true : undefined} aria-describedby={errors.problem ? "problem-error" : undefined} onChange={(e) => setFields({ ...fields, problem: e.target.value })} />
              </Field>
              <Field id="solution" label="Solution and key features" error={errors.solution} hint="Paste the description, or upload a .txt or .md file below.">
                <textarea id="solution" rows={8} className={input} value={fields.solution} aria-invalid={errors.solution ? true : undefined} aria-describedby={errors.solution ? "solution-error" : undefined} onChange={(e) => setFields({ ...fields, solution: e.target.value })} />
              </Field>
              <div>
                <label htmlFor="file" className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-navy-300 px-4 py-2 text-sm font-semibold text-navy hover:bg-navy-50 focus-within:ring-2 focus-within:ring-teal-600">
                  <Upload className="h-4 w-4" aria-hidden="true" /> Upload .txt or .md
                </label>
                <input id="file" type="file" accept=".txt,.md,text/plain,text/markdown" className="sr-only" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
              </div>
            </>
          )}

          {step === 1 && (
            <>
              <div className="flex flex-wrap items-center justify-between gap-3">
                <p className="text-base text-stone-700">Each element is one feature a reference must disclose. Edit, split, merge and reorder until they match your claim.</p>
                <div className="flex gap-2">
                  <Button variant="outline" size="sm" disabled={extract.isPending} onClick={() => extract.mutate()}>
                    <Sparkles className="h-4 w-4" aria-hidden="true" /> {extract.isPending ? "Extracting..." : "Extract from disclosure"}
                  </Button>
                  <Button variant="outline" size="sm" onClick={() => setElements((l) => [...l, { uid: uid(), text: "", source: "user" }])}>
                    <Plus className="h-4 w-4" aria-hidden="true" /> Add element
                  </Button>
                </div>
              </div>
              {elements.length === 0 && <p className="rounded-lg border border-dashed border-stone-300 p-6 text-center text-stone-700">No elements yet. Extract them from the disclosure or add them by hand.</p>}
              <ol className="space-y-3">
                {elements.map((el, i) => (
                  <li key={el.uid} className="rounded-xl border border-stone-200 p-3">
                    <div className="flex gap-3">
                      <span className="mt-2 w-8 shrink-0 font-mono text-sm font-semibold text-teal-700">E{i + 1}</span>
                      <div className="min-w-0 flex-1">
                        <label htmlFor={`el-${el.uid}`} className="sr-only">Element {i + 1}</label>
                        <textarea
                          id={`el-${el.uid}`}
                          rows={2}
                          className={input}
                          value={el.text}
                          onSelect={(e) => (cursors.current[el.uid] = e.currentTarget.selectionStart)}
                          onChange={(e) => setEl(i, { text: e.target.value })}
                        />
                        <p className="mt-1 text-xs text-stone-600">{el.source === "user" ? "Written or edited by you" : el.source === "llm" ? "Extracted by the language model" : "Extracted locally"}</p>
                      </div>
                      <div className="flex shrink-0 flex-col gap-1 sm:flex-row">
                        <Button variant="ghost" size="sm" aria-label={`Move element ${i + 1} up`} disabled={i === 0} onClick={() => setElements((l) => moveItem(l, i, i - 1))}><ArrowUp className="h-4 w-4" aria-hidden="true" /></Button>
                        <Button variant="ghost" size="sm" aria-label={`Move element ${i + 1} down`} disabled={i === elements.length - 1} onClick={() => setElements((l) => moveItem(l, i, i + 1))}><ArrowDown className="h-4 w-4" aria-hidden="true" /></Button>
                        <Button variant="ghost" size="sm" aria-label={`Split element ${i + 1} at the cursor`} onClick={() => setElements((l) => splitElement(l, i, cursors.current[el.uid] ?? Math.floor(el.text.length / 2), uid()))}><Scissors className="h-4 w-4" aria-hidden="true" /></Button>
                        <Button variant="ghost" size="sm" aria-label={`Merge element ${i + 1} with the next`} disabled={i === elements.length - 1} onClick={() => setElements((l) => mergeWithNext(l, i))}><GitMerge className="h-4 w-4" aria-hidden="true" /></Button>
                        <Button variant="ghost" size="sm" aria-label={`Delete element ${i + 1}`} onClick={() => setElements((l) => l.filter((_, j) => j !== i))}><Trash2 className="h-4 w-4 text-risk-high" aria-hidden="true" /></Button>
                      </div>
                    </div>
                  </li>
                ))}
              </ol>
            </>
          )}

          {step === 2 && (
            <>
              <Field id="priority" label="Priority date (optional)" hint="References published after this date are not prior art.">
                <input id="priority" type="date" className={`${input} max-w-xs`} value={priorityDate} onChange={(e) => setPriorityDate(e.target.value)} />
              </Field>
              <Field id="refs" label={`References to chart: ${references}`} hint="More references cost more model tokens. Three is a good start.">
                <input id="refs" type="range" min={1} max={5} value={references} onChange={(e) => setReferences(Number(e.target.value))} className="w-full max-w-xs accent-teal-700" />
              </Field>
              <Field id="mode" label="Language model mode for this case">
                <select id="mode" className={`${input} max-w-md`} value={llmMode} onChange={(e) => setLlmMode(e.target.value as LlmMode)}>
                  {MODES.map((m) => <option key={m.value} value={m.value}>{m.label}</option>)}
                </select>
              </Field>
              <p className="text-sm text-stone-600">Classification (CPC) suggestions appear in the search results after the first run, based on where the best references cluster.</p>
            </>
          )}

          {step === 3 && (
            <>
              <dl className="grid gap-3 sm:grid-cols-2">
                {[
                  ["Title", fields.title],
                  ["Elements", String(filled)],
                  ["Priority date", priorityDate || "Not set"],
                  ["References to chart", String(references)],
                  ["Language model mode", MODES.find((m) => m.value === llmMode)?.label ?? llmMode],
                ].map(([k, v]) => (
                  <div key={k} className="rounded-lg bg-stone-50 p-3">
                    <dt className="text-xs font-semibold uppercase tracking-wide text-stone-600">{k}</dt>
                    <dd className="mt-0.5 text-base text-navy">{v}</dd>
                  </div>
                ))}
              </dl>
              <div role="note" className="rounded-lg border border-teal-200 bg-teal-50 p-4 text-sm text-teal-900">
                {llmMode === "local_only"
                  ? "Nothing will leave this server. Charting uses local matching only."
                  : "Only the disclosure text needed for each step is sent to the configured model provider. Quoted passages are checked against the source before they are shown."}
              </div>
            </>
          )}

          <div className="flex items-center justify-between border-t border-stone-200 pt-5">
            <div className="flex items-center gap-3">
              <Button variant="outline" disabled={step === 0 || (step === 1 && create.isPending)} onClick={() => setStep(step - 1)}>Back</Button>
              <p className="text-sm text-stone-600" aria-live="polite">
                {saved === "saving" ? "Saving draft..." : saved === "saved" ? "Draft saved" : saved === "error" ? "Could not save the draft" : caseId ? "" : "Draft kept in this browser"}
              </p>
            </div>
            {step < 3 ? (
              <Button onClick={next} disabled={create.isPending}>{create.isPending ? "Saving..." : step === 0 ? "Save and continue" : "Continue"}</Button>
            ) : (
              <Button onClick={() => run.mutate()} disabled={run.isPending || filled === 0}>{run.isPending ? "Starting..." : "Run analysis"}</Button>
            )}
          </div>
        </CardContent>
      </Card>
    </>
  );
}
