import { LazyMotion, m, useReducedMotion } from "framer-motion";
import type { ReactNode } from "react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

const loadFeatures = () => import("@/lib/motion-features").then((mod) => mod.default);

export function Container({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("container", className)}>{children}</div>;
}

/** Fade and rise on scroll. Renders plain content when the visitor prefers reduced motion. */
export function Reveal({ children, className, delay = 0 }: { children: ReactNode; className?: string; delay?: number }) {
  const reduce = useReducedMotion();
  if (reduce) return <div className={className}>{children}</div>;
  // Animation features load after first paint, so they never hold up the initial render.
  return (
    <LazyMotion features={loadFeatures} strict>
      <m.div
        className={className}
        initial={{ opacity: 0, y: 16 }}
        whileInView={{ opacity: 1, y: 0 }}
        viewport={{ once: true, margin: "-60px" }}
        transition={{ duration: 0.45, delay, ease: "easeOut" }}
      >
        {children}
      </m.div>
    </LazyMotion>
  );
}

export function Section({
  id,
  eyebrow,
  title,
  intro,
  children,
  tone = "white",
  className,
}: {
  id?: string;
  eyebrow?: string;
  title?: string;
  intro?: string;
  children: ReactNode;
  tone?: "white" | "muted" | "navy";
  className?: string;
}) {
  const dark = tone === "navy";
  return (
    <section
      id={id}
      aria-labelledby={id && title ? `${id}-title` : undefined}
      className={cn(
        "py-16 md:py-24",
        tone === "muted" && "bg-stone-50",
        dark && "on-dark bg-navy text-white",
        className,
      )}
    >
      <Container>
        {(eyebrow || title || intro) && (
          <Reveal className="mb-10 max-w-3xl md:mb-14">
            {eyebrow && <p className={cn("eyebrow", dark && "text-teal-200")}>{eyebrow}</p>}
            {title && (
              <h2 id={id ? `${id}-title` : undefined} className={cn("text-2xl md:text-3xl", dark && "text-white")}>
                {title}
              </h2>
            )}
            {intro && <p className={cn("mt-4 text-lg", dark ? "text-navy-100" : "text-stone-700")}>{intro}</p>}
          </Reveal>
        )}
        {children}
      </Container>
    </section>
  );
}

export function PageHero({ eyebrow, title, intro }: { eyebrow: string; title: string; intro: string }) {
  return (
    <header className="mesh border-b border-stone-200 py-14 md:py-20">
      <Container>
        <p className="eyebrow">{eyebrow}</p>
        <h1 className="max-w-3xl text-2xl sm:text-3xl md:text-3xl">{title}</h1>
        <p className="mt-5 max-w-2xl text-lg text-stone-700">{intro}</p>
      </Container>
    </header>
  );
}

export function CtaBanner({ title, text }: { title: string; text: string }) {
  return (
    <section className="on-dark bg-navy py-16 text-white md:py-20" aria-labelledby="cta-title">
      <Container className="flex flex-col items-start justify-between gap-8 md:flex-row md:items-center">
        <div className="max-w-2xl">
          <h2 id="cta-title" className="text-2xl text-white md:text-3xl">
            {title}
          </h2>
          <p className="mt-3 text-lg text-navy-100">{text}</p>
        </div>
        <div className="flex flex-wrap gap-3">
          <Button asChild variant="light" size="lg">
            <Link to="/contact?topic=demo">Request a demo</Link>
          </Button>
          <Button asChild variant="outlineLight" size="lg">
            <Link to="/login">Log in</Link>
          </Button>
        </div>
      </Container>
    </section>
  );
}
