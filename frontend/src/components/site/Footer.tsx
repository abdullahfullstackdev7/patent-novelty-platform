import { Github, Linkedin, Twitter } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Logo } from "@/components/site/Header";
import { Container } from "@/components/site/primitives";
import { Button } from "@/components/ui/button";
import { FOOTER_COLUMNS } from "@/content/site";

const NEWSLETTER_KEY = "priorart.newsletter";

function Newsletter() {
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");

  function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const email = String(new FormData(event.currentTarget).get("email") ?? "").trim();
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      setError("Enter a valid email address");
      return;
    }
    try {
      localStorage.setItem(NEWSLETTER_KEY, email); // stored on this device only; there is no mailing list yet
    } catch {
      /* storage may be blocked */
    }
    setError("");
    setDone(true);
  }

  if (done) return <p role="status">Thanks. We have noted your interest on this device.</p>;
  return (
    <form onSubmit={submit} noValidate className="flex max-w-sm flex-col gap-2 sm:flex-row" aria-label="Newsletter">
      <div className="flex-1">
        <label htmlFor="newsletter-email" className="sr-only">
          Email address
        </label>
        <input
          id="newsletter-email"
          name="email"
          type="email"
          autoComplete="email"
          placeholder="you@company.com"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "newsletter-error" : undefined}
          className="h-11 w-full rounded-lg border border-navy-300 bg-white px-3 text-base text-navy placeholder:text-stone-500"
        />
        {error && (
          <p id="newsletter-error" className="mt-1 text-sm text-red-200">
            {error}
          </p>
        )}
      </div>
      <Button type="submit" variant="light">
        Subscribe
      </Button>
    </form>
  );
}

export function Footer() {
  return (
    <footer className="on-dark bg-navy text-navy-100">
      <Container className="py-14">
        <div className="grid gap-10 lg:grid-cols-[1.2fr_repeat(5,1fr)]">
          <div className="lg:pr-6">
            <Logo light />
            <p className="mt-4 max-w-xs text-sm">Prior-art intelligence for confident patent decisions.</p>
            <div className="mt-5">
              <p className="mb-2 text-sm font-semibold text-white">Product news</p>
              <Newsletter />
            </div>
          </div>
          {FOOTER_COLUMNS.map((column) => (
            <nav key={column.title} aria-label={column.title}>
              <p className="mb-3 text-sm font-semibold uppercase tracking-wider text-white">{column.title}</p>
              <ul className="space-y-2 text-sm">
                {column.links.map((link) => (
                  <li key={link.to + link.label}>
                    <Link to={link.to} className="hover:text-white hover:underline">
                      {link.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </nav>
          ))}
        </div>

        <div className="mt-12 flex flex-col gap-6 border-t border-white/15 pt-8 text-sm">
          <p>
            Patent data: PatentsView (USPTO, licensed CC BY 4.0) and the Harvard USPTO Patent Dataset, HUPD (CC BY-SA 4.0).{" "}
            <Link to="/legal/attributions" className="underline hover:text-white">
              Attributions
            </Link>
            .
          </p>
          <p>
            Customer names, logos, testimonials, stories and team profiles on this site are sample content for demonstration
            purposes and do not describe real organisations or people.
          </p>
          <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-center">
            <p>&copy; {new Date().getFullYear()} PriorArt Atlas. All rights reserved.</p>
            <ul className="flex gap-4" aria-label="Social media">
              {[
                { Icon: Linkedin, label: "LinkedIn" },
                { Icon: Twitter, label: "X (Twitter)" },
                { Icon: Github, label: "GitHub" },
              ].map(({ Icon, label }) => (
                <li key={label}>
                  <a href="https://example.com" rel="noopener noreferrer" aria-label={label} className="hover:text-white">
                    <Icon className="h-5 w-5" aria-hidden="true" />
                  </a>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </Container>
    </footer>
  );
}
