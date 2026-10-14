import { Lock } from "lucide-react";
import { Link, useParams } from "react-router-dom";

import { Container, CtaBanner, PageHero, Reveal, Section } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent } from "@/components/ui/card";
import { ARTICLES, findArticle } from "@/content/articles";
import { SECURITY_CONTROLS, TEAM, VALUES } from "@/content/site";
import { Seo } from "@/lib/seo";
import NotFound from "@/pages/NotFound";

export function Security() {
  return (
    <>
      <Seo title="Security" description="How PriorArt Atlas protects disclosures, reports and account access." path="/security" />
      <PageHero
        eyebrow="Security"
        title="Confidential work deserves careful engineering"
        intro="These are the controls implemented in the product today. We do not claim certifications we do not hold."
      />
      <Section>
        <div className="grid gap-6 md:grid-cols-2">
          {SECURITY_CONTROLS.map((c) => (
            <Reveal key={c.title}>
              <Card className="h-full">
                <CardContent>
                  <h2 className="flex items-center gap-2 text-lg">
                    <Lock className="h-5 w-5 text-teal-700" aria-hidden="true" />
                    {c.title}
                  </h2>
                  <p className="mt-2 text-base text-stone-700">{c.text}</p>
                </CardContent>
              </Card>
            </Reveal>
          ))}
        </div>
        <p className="mt-8 max-w-3xl text-base text-stone-700">
          The product has not yet been independently audited or certified. Questions from your security team are welcome through the{" "}
          <Link to="/contact?topic=sales" className="font-semibold text-teal-700 underline">
            contact form
          </Link>
          .
        </p>
      </Section>
      <CtaBanner title="Have a security questionnaire?" text="Send it over and we will answer it in writing." />
    </>
  );
}

export function About() {
  return (
    <>
      <Seo title="About" description="Our mission, values and team." path="/about" />
      <PageHero eyebrow="About" title="We build tools that show their work" intro="Our mission is to make prior-art review faster without making it less trustworthy." />
      <Section eyebrow="Values" title="What we hold ourselves to">
        <div className="grid gap-6 md:grid-cols-3">
          {VALUES.map((v) => (
            <Card key={v.title}>
              <CardContent>
                <v.icon className="mb-3 h-7 w-7 text-teal-700" aria-hidden="true" />
                <h3 className="text-lg">{v.title}</h3>
                <p className="mt-2 text-base text-stone-700">{v.text}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </Section>
      <Section tone="muted" eyebrow="Leadership" title="The team" intro="Sample profiles for the demonstration build. These are fictional people.">
        <div className="grid gap-6 md:grid-cols-3">
          {TEAM.map((m) => (
            <Card key={m.name}>
              <CardContent>
                <div
                  className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-navy text-lg font-semibold text-white"
                  aria-hidden="true"
                >
                  {m.name
                    .split(" ")
                    .map((w) => w[0])
                    .join("")}
                </div>
                <h3 className="text-lg">{m.name}</h3>
                <p className="text-sm font-medium text-teal-700">{m.role}</p>
                <p className="mt-2 text-base text-stone-700">{m.bio}</p>
                <Badge className="mt-3" tone="teal">
                  Sample profile
                </Badge>
              </CardContent>
            </Card>
          ))}
        </div>
      </Section>
      <CtaBanner title="Talk to the team" text="We read every message and reply within two business days." />
    </>
  );
}

export function Resources() {
  return (
    <>
      <Seo title="Resources" description="Guides on prior-art searching, claim charts and the difference between novelty and obviousness." path="/resources" />
      <PageHero eyebrow="Resources" title="Guides for IP professionals" intro="Short, practical explanations written for people who do this work every day." />
      <Section>
        <div className="grid gap-6 md:grid-cols-3">
          {ARTICLES.map((a) => (
            <Card key={a.slug} className="h-full">
              <CardContent>
                <p className="text-sm text-stone-600">
                  {a.readMinutes} min read &middot; <time dateTime={a.published}>{a.published}</time>
                </p>
                <h2 className="mt-2 text-lg">
                  <Link to={`/resources/${a.slug}`} className="hover:text-teal-700 hover:underline">
                    {a.title}
                  </Link>
                </h2>
                <p className="mt-2 text-base text-stone-700">{a.summary}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </Section>
    </>
  );
}

export function ResourceArticle() {
  const { slug } = useParams();
  const article = findArticle(slug);
  if (!article) return <NotFound />;
  return (
    <>
      <Seo title={article.title} description={article.summary} path={`/resources/${article.slug}`} />
      <PageHero eyebrow="Resources" title={article.title} intro={article.summary} />
      <Container className="py-12 md:py-16">
        <article className="prose-article mx-auto max-w-2xl">
          <p className="mb-8 text-sm text-stone-600">
            {article.readMinutes} min read &middot; <time dateTime={article.published}>{article.published}</time>
          </p>
          {article.sections.map((s, i) => (
            <section key={i}>
              {s.heading && <h2>{s.heading}</h2>}
              {s.paragraphs?.map((p) => <p key={p}>{p}</p>)}
              {s.bullets && (
                <ul>
                  {s.bullets.map((b) => (
                    <li key={b}>{b}</li>
                  ))}
                </ul>
              )}
            </section>
          ))}
          <p className="text-base">
            This article is general information, not legal advice.
          </p>
          <Button asChild variant="outline" className="mt-6">
            <Link to="/resources">Back to all resources</Link>
          </Button>
        </article>
      </Container>
    </>
  );
}
