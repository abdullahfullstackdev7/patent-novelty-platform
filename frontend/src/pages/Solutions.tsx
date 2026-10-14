import { Link } from "react-router-dom";

import { Container, CtaBanner, PageHero, Reveal } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { SOLUTIONS } from "@/content/site";
import { Seo } from "@/lib/seo";

export default function Solutions() {
  return (
    <>
      <Seo title="Solutions" description="How patent attorneys, corporate IP counsel, R&D teams and universities use PriorArt Atlas." path="/solutions" />
      <PageHero
        eyebrow="Solutions"
        title="The same evidence-first method, shaped to your role"
        intro="Whether you write opinions, screen disclosures or triage a backlog, you start from charted references and finish with a reviewed report."
      />
      <Container className="divide-y divide-stone-200 py-8">
        {SOLUTIONS.map((role) => (
          <section key={role.id} id={role.id} aria-labelledby={`${role.id}-title`} className="grid gap-8 py-12 md:grid-cols-[1fr_1.3fr]">
            <Reveal>
              <h2 id={`${role.id}-title`} className="text-xl md:text-2xl">
                {role.title}
              </h2>
              <p className="mt-3 text-lg text-stone-700">{role.summary}</p>
            </Reveal>
            <Reveal>
              <ul className="space-y-4 text-lg text-stone-700">
                {role.bullets.map((b) => (
                  <li key={b} className="flex gap-3">
                    <span aria-hidden="true" className="mt-3 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-600" />
                    {b}
                  </li>
                ))}
              </ul>
              <Button asChild variant="outline" className="mt-6">
                <Link to={`/contact?topic=demo&role=${role.id}`}>Request a demo for {role.title.toLowerCase()}</Link>
              </Button>
            </Reveal>
          </section>
        ))}
      </Container>
      <CtaBanner title="Find the workflow that fits your team" text="Tell us how disclosures reach you today and we will show the shortest path to a reviewed report." />
    </>
  );
}
