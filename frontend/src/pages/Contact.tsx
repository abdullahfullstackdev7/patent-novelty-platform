import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { useSearchParams } from "react-router-dom";

import { Container, PageHero } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ApiError, sendContact } from "@/lib/api";
import { contactSchema, type ContactInput } from "@/lib/forms";
import { Seo } from "@/lib/seo";

const TOPICS: { value: ContactInput["topic"]; label: string }[] = [
  { value: "demo", label: "Request a demo" },
  { value: "sales", label: "Talk to sales" },
  { value: "support", label: "Support" },
  { value: "other", label: "Something else" },
];

function Field({ id, label, error, children }: { id: string; label: string; error?: string; children: React.ReactNode }) {
  return (
    <div>
      <label htmlFor={id} className="mb-1.5 block text-sm font-semibold text-navy">
        {label}
      </label>
      {children}
      {error && (
        <p id={`${id}-error`} role="alert" className="mt-1 text-sm text-risk-high">
          {error}
        </p>
      )}
    </div>
  );
}

const inputClass =
  "w-full rounded-lg border border-navy-300 bg-white px-3 py-2.5 text-base text-navy placeholder:text-stone-500 aria-[invalid=true]:border-risk-high";

export default function Contact() {
  const [params] = useSearchParams();
  const topicParam = params.get("topic");
  const topic = TOPICS.some((t) => t.value === topicParam) ? (topicParam as ContactInput["topic"]) : "demo";

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ContactInput>({ resolver: zodResolver(contactSchema), defaultValues: { topic } });

  const send = useMutation({ mutationFn: sendContact, onSuccess: () => reset({ topic }) });

  const invalid = (name: keyof ContactInput) => (errors[name] ? { "aria-invalid": true, "aria-describedby": `${name}-error` } : {});

  return (
    <>
      <Seo title="Contact" description="Request a demo, talk to sales or get support." path="/contact" />
      <PageHero eyebrow="Contact" title="Tell us what you are working on" intro="We reply within two business days. Messages are stored securely and used only to respond to you." />
      <Container className="grid gap-10 py-14 lg:grid-cols-[1.4fr_1fr]">
        <Card>
          <CardContent>
            {send.isSuccess ? (
              <div role="status">
                <h2 className="text-xl">Thank you, your message was received</h2>
                <p className="mt-2 text-lg text-stone-700">Someone from the team will reply by email.</p>
                <Button className="mt-6" variant="outline" onClick={() => send.reset()}>
                  Send another message
                </Button>
              </div>
            ) : (
              <form onSubmit={handleSubmit((values) => send.mutate(values))} noValidate className="space-y-5" aria-label="Contact form">
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field id="name" label="Full name" error={errors.name?.message}>
                    <input id="name" autoComplete="name" className={inputClass} {...invalid("name")} {...register("name")} />
                  </Field>
                  <Field id="email" label="Work email" error={errors.email?.message}>
                    <input id="email" type="email" autoComplete="email" className={inputClass} {...invalid("email")} {...register("email")} />
                  </Field>
                </div>
                <div className="grid gap-5 sm:grid-cols-2">
                  <Field id="organization" label="Organisation (optional)" error={errors.organization?.message}>
                    <input id="organization" autoComplete="organization" className={inputClass} {...register("organization")} />
                  </Field>
                  <Field id="topic" label="Topic" error={errors.topic?.message}>
                    <select id="topic" className={inputClass} {...register("topic")}>
                      {TOPICS.map((t) => (
                        <option key={t.value} value={t.value}>
                          {t.label}
                        </option>
                      ))}
                    </select>
                  </Field>
                </div>
                <Field id="message" label="How can we help?" error={errors.message?.message}>
                  <textarea id="message" rows={6} className={inputClass} {...invalid("message")} {...register("message")} />
                </Field>
                {/* Honeypot: invisible to people and assistive technology, tempting to bots. */}
                <div aria-hidden="true" className="absolute -left-[9999px] h-0 w-0 overflow-hidden">
                  <label htmlFor="website">Leave this field empty</label>
                  <input id="website" tabIndex={-1} autoComplete="off" {...register("website")} />
                </div>
                {send.isError && (
                  <p role="alert" className="text-base text-risk-high">
                    {send.error instanceof ApiError && send.error.status === 429
                      ? "You have sent several messages recently. Please try again later."
                      : "We could not send your message. Please check the details and try again."}
                  </p>
                )}
                <Button type="submit" size="lg" disabled={send.isPending}>
                  {send.isPending ? "Sending..." : "Send message"}
                </Button>
              </form>
            )}
          </CardContent>
        </Card>
        <aside className="space-y-4 text-base text-stone-700" aria-label="Other ways to reach us">
          <h2 className="text-lg">What happens next</h2>
          <ol className="list-decimal space-y-2 pl-5">
            <li>We read your message and match it to the right person.</li>
            <li>We reply by email to arrange a walkthrough or answer your question.</li>
            <li>For demos, we prepare a sample case in your technology area.</li>
          </ol>
        </aside>
      </Container>
    </>
  );
}
