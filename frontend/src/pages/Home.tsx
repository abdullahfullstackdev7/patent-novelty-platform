import { ArrowRight, Lock } from "lucide-react";
import { Link } from "react-router-dom";

import { PricingCards } from "@/components/site/PricingCards";
import { ClaimChartMock, TourPanel } from "@/components/site/ProductMock";
import { Container, CtaBanner, Reveal, Section } from "@/components/site/primitives";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Skeleton } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ARTICLES } from "@/content/articles";
import { CAPABILITIES, FAQ, SAMPLE_FIRMS, SECURITY_CONTROLS, SOLUTIONS, STEPS, STORIES, TOUR } from "@/content/site";
import { useStats } from "@/lib/queries";
import { Seo } from "@/lib/seo";
import { formatCount } from "@/lib/utils";

function KeyFigures() {
  const stats = useStats();
  const corpus = stats.data ? formatCount(stats.data.patents) : null;
  const items = [
    { value: corpus, fallback: stats.isError ? "n/a" : null, label: "patent documents in the demo index" },
    { value: "Under 5 min", label: "from disclosure to draft report" },
    { value: "100%", label: "of quoted excerpts verified against the source" },
    { value: "Built in", label: "attorney review and sign-off" },
  ];
  return (
    <section aria-label="Key figures" className="border-y border-stone-200 bg-stone-50 py-12">
      <Container>
        <dl className="grid grid-cols-2 gap-8 lg:grid-cols-4">
          {items.map((item) => (
            <Reveal key={item.label} className="flex flex-col-reverse">
              <dt className="mt-1 text-base text-stone-700">{item.label}</dt>
              <dd className="text-2xl font-semibold text-navy md:text-3xl">
                {item.value ?? item.fallback ?? <Skeleton className="h-9 w-28" />}
              </dd>
            </Reveal>
          ))}
        </dl>
        <p className="mt-6 text-sm text-stone-600">
          The index count is read from the database behind this demo and reflects only the documents loaded into it.
        </p>
      </Container>
    </section>
  );
}

export default function Home() {
  return (
    <>
      <Seo
        title="PriorArt Atlas"
        description="Search US patent records semantically, chart every claim element against the closest references and deliver attorney-ready novelty reports in minutes."
        path="/"
      />

      {/* 1. Hero */}
      <section className="mesh" aria-labelledby="hero-title">
        <Container className="grid items-center gap-12 py-14 md:py-20 lg:grid-cols-2">
          <div>
            <p className="eyebrow">Patent novelty and prior-art platform</p>
            <h1 id="hero-title" className="text-2xl sm:text-3xl lg:text-3xl xl:text-4xl">
              Prior-art intelligence for confident patent decisions
            </h1>
            <p className="mt-5 max-w-xl text-lg text-stone-700">
              Search millions of US patent records semantically, chart every claim element against the closest references, and
              deliver attorney-ready novelty reports in minutes.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Button asChild size="lg">
                <Link to="/contact?topic=demo">Request a demo</Link>
              </Button>
              <Button asChild variant="outline" size="lg">
                <Link to="/login">Log in</Link>
              </Button>
            </div>
          </div>
          <div className="relative">
            <ClaimChartMock compact />
            <div className="absolute -bottom-5 left-3 hidden rounded-xl border border-stone-200 bg-white px-4 py-3 shadow-card sm:block">
              <p className="text-xs text-stone-600">Novelty risk</p>
              <Badge tone="medium">Medium</Badge>
            </div>
            <div className="absolute -top-4 right-3 hidden rounded-xl border border-stone-200 bg-white px-4 py-3 shadow-card sm:block">
              <p className="text-xs text-stone-600">Obviousness risk</p>
              <Badge tone="low">Low</Badge>
            </div>
          </div>
        </Container>
      </section>

      {/* 2. Trust band */}
      <section aria-labelledby="trust-title" className="py-12">
        <Container>
          <h2 id="trust-title" className="mb-6 text-center text-base font-semibold text-stone-600">
            Trusted by IP teams worldwide
          </h2>
          <ul className="flex flex-wrap items-center justify-center gap-x-10 gap-y-4">
            {SAMPLE_FIRMS.map((firm) => (
              <li key={firm} className="font-semibold tracking-wide text-stone-500 [font-variant:small-caps]" aria-label={`${firm} (sample)`}>
                {firm}
              </li>
            ))}
          </ul>
          <p className="mt-5 text-center text-sm text-stone-600">Sample content: the firms above are fictional.</p>
        </Container>
      </section>

      {/* 3. Key figures */}
      <KeyFigures />

      {/* 4. How it works */}
      <Section id="how" eyebrow="How it works" title="From disclosure to reviewed report in five steps">
        <ol className="grid gap-6 sm:grid-cols-2 lg:grid-cols-5">
          {STEPS.map((step, i) => (
            <li key={step.title} className="list-none">
              <Reveal delay={i * 0.05} className="h-full">
                <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-xl bg-teal-50 text-teal-700">
                  <step.icon className="h-6 w-6" aria-hidden="true" />
                </div>
                <h3 className="text-lg">
                  <span className="mr-1 text-teal-700">{i + 1}.</span>
                  {step.title}
                </h3>
                <p className="mt-2 text-base text-stone-700">{step.text}</p>
              </Reveal>
            </li>
          ))}
        </ol>
      </Section>

      {/* 5. Capabilities */}
      <Section id="capabilities" tone="muted" eyebrow="Platform" title="Everything a novelty review needs in one place">
        <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-3">
          {CAPABILITIES.map((item, i) => (
            <Reveal key={item.title} delay={(i % 3) * 0.05}>
              <Card className="h-full">
                <CardContent>
                  <item.icon className="mb-4 h-7 w-7 text-teal-700" aria-hidden="true" />
                  <h3 className="text-lg">{item.title}</h3>
                  <p className="mt-2 text-base text-stone-700">{item.text}</p>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 6. Product tour */}
      <Section id="tour" eyebrow="Product tour" title="See the workflow">
        <Tabs defaultValue={TOUR[0].id}>
          <TabsList aria-label="Product tour views">
            {TOUR.map((tab) => (
              <TabsTrigger key={tab.id} value={tab.id}>
                {tab.label}
              </TabsTrigger>
            ))}
          </TabsList>
          {TOUR.map((tab) => (
            <TabsContent key={tab.id} value={tab.id} className="grid items-center gap-8 lg:grid-cols-[1fr_1.2fr]">
              <div>
                <h3 className="text-xl">{tab.title}</h3>
                <p className="mt-3 text-lg text-stone-700">{tab.text}</p>
              </div>
              <TourPanel title={tab.label} rows={tab.rows} />
            </TabsContent>
          ))}
        </Tabs>
        <p className="mt-6 text-sm text-stone-600">Illustrations show sample data and will be replaced with captures from the application.</p>
      </Section>

      {/* 7. Solutions */}
      <Section id="solutions" tone="muted" eyebrow="Solutions" title="Built for the people who make patent decisions">
        <div className="grid gap-6 md:grid-cols-2">
          {SOLUTIONS.map((role) => (
            <Reveal key={role.id}>
              <Card className="h-full">
                <CardContent>
                  <h3 className="text-xl">{role.title}</h3>
                  <ul className="mt-4 space-y-2 text-base text-stone-700">
                    {role.bullets.map((b) => (
                      <li key={b} className="flex gap-2">
                        <span aria-hidden="true" className="mt-2.5 h-1.5 w-1.5 shrink-0 rounded-full bg-teal-600" />
                        {b}
                      </li>
                    ))}
                  </ul>
                  <Link to={`/solutions#${role.id}`} className="mt-5 inline-flex items-center gap-1 font-semibold text-teal-700 hover:underline">
                    Learn more <ArrowRight className="h-4 w-4" aria-hidden="true" />
                    <span className="sr-only"> about {role.title}</span>
                  </Link>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 8. Security */}
      <Section id="security" tone="navy" eyebrow="Security and governance" title="Controls that are built in and verifiable">
        <div className="grid gap-x-10 gap-y-8 md:grid-cols-2">
          {SECURITY_CONTROLS.slice(0, 4).map((c) => (
            <Reveal key={c.title}>
              <h3 className="flex items-center gap-2 text-lg text-white">
                <Lock className="h-5 w-5 text-teal-200" aria-hidden="true" />
                {c.title}
              </h3>
              <p className="mt-2 text-base text-navy-100">{c.text}</p>
            </Reveal>
          ))}
        </div>
        <Button asChild variant="light" className="mt-10">
          <Link to="/security">Read the security overview</Link>
        </Button>
      </Section>

      {/* 9. Stories */}
      <Section id="stories" eyebrow="Customer stories" title="What teams use it for">
        <div className="grid gap-6 md:grid-cols-3">
          {STORIES.map((story) => (
            <Reveal key={story.org}>
              <Card className="h-full">
                <CardContent>
                  <Badge tone="teal">Sample story</Badge>
                  <p className="mt-4 text-3xl font-semibold text-navy md:text-3xl">{story.metric}</p>
                  <p className="text-base font-medium text-stone-700">{story.label}</p>
                  <p className="mt-4 text-base text-stone-700">{story.text}</p>
                  <p className="mt-4 text-sm font-semibold text-navy">{story.org}</p>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 10. Insights */}
      <Section id="insights" tone="muted" eyebrow="Insights and resources" title="Practical guides for IP professionals">
        <div className="grid gap-6 md:grid-cols-3">
          {ARTICLES.map((a) => (
            <Reveal key={a.slug}>
              <Card className="h-full">
                <CardContent>
                  <p className="text-sm text-stone-600">{a.readMinutes} min read</p>
                  <h3 className="mt-2 text-lg">
                    <Link to={`/resources/${a.slug}`} className="hover:text-teal-700 hover:underline">
                      {a.title}
                    </Link>
                  </h3>
                  <p className="mt-2 text-base text-stone-700">{a.summary}</p>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
      </Section>

      {/* 11. Pricing preview */}
      <Section id="pricing" eyebrow="Pricing" title="Simple plans that grow with your caseload" intro="Prices below are read from the demo billing plans.">
        <PricingCards />
        <p className="mt-6">
          <Link to="/pricing" className="font-semibold text-teal-700 hover:underline">
            Compare plans in detail
          </Link>
        </p>
      </Section>

      {/* 12. FAQ */}
      <Section id="faq" tone="muted" eyebrow="FAQ" title="Questions we are asked most">
        <Accordion type="single" collapsible className="max-w-3xl">
          {FAQ.map((item, i) => (
            <AccordionItem key={item.q} value={`q${i}`}>
              <AccordionTrigger>{item.q}</AccordionTrigger>
              <AccordionContent>{item.a}</AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      </Section>

      {/* 13. Final CTA (footer is in the layout) */}
      <CtaBanner title="See your next novelty review in action" text="Book a walkthrough with sample cases, or sign in if your team already has an account." />
    </>
  );
}
