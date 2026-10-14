import { Link } from "react-router-dom";

import { PricingCards } from "@/components/site/PricingCards";
import { Container, CtaBanner, PageHero, Section } from "@/components/site/primitives";
import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from "@/components/ui/accordion";
import { Skeleton } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Plan } from "@/lib/api";
import { usePlans } from "@/lib/queries";
import { Seo } from "@/lib/seo";
import { formatMoney } from "@/lib/utils";

const PRICING_FAQ = [
  { q: "What counts as a report?", a: "One report is metered per case, the first time its report is generated. Re-running the analysis or creating new report versions for the same case is not billed again." },
  { q: "What happens if we use more than the included reports?", a: "Additional reports are billed at the overage price shown for your plan on the invoice for that month. Nothing is blocked." },
  { q: "Can we change plans or seats?", a: "Yes. Changes take effect from the date you choose and invoices show each part separately." },
  { q: "How are invoices issued?", a: "Monthly in arrears, with a line for the subscription, one for any additional seats and one for overage, each with quantity and unit price." },
];

function Comparison() {
  const plans = usePlans();
  if (plans.isError) return <p role="alert">Plan details could not be loaded. Please contact sales.</p>;
  if (!plans.data) return <Skeleton className="h-56" />;
  const data = plans.data;
  const rows: { label: string; value: (p: Plan) => string }[] = [
    { label: "Monthly price", value: (p) => formatMoney(p.monthly_price) },
    { label: "Included reports per month", value: (p) => String(p.included_reports) },
    { label: "Price per additional report", value: (p) => formatMoney(p.overage_price) },
    { label: "Included seats", value: (p) => String(p.seats) },
    { label: "Price per additional seat", value: (p) => (p.extra_seat_price > 0 ? formatMoney(p.extra_seat_price) : "Not applicable") },
  ];
  return (
    <Table>
      <caption className="sr-only">Plan comparison</caption>
      <TableHead>
        <TableRow>
          <TableHeader scope="col">Feature</TableHeader>
          {data.map((p) => (
            <TableHeader key={p.code} scope="col">
              {p.name}
            </TableHeader>
          ))}
        </TableRow>
      </TableHead>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.label}>
            <TableHeader scope="row" className="font-medium">
              {row.label}
            </TableHeader>
            {data.map((p) => (
              <TableCell key={p.code}>{row.value(p)}</TableCell>
            ))}
          </TableRow>
        ))}
        {["Hybrid search and claim charts", "Risk scoring and review workflow", "PDF reports and CSV analytics export"].map((label) => (
          <TableRow key={label}>
            <TableHeader scope="row" className="font-medium">
              {label}
            </TableHeader>
            {data.map((p) => (
              <TableCell key={p.code}>Included</TableCell>
            ))}
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export default function Pricing() {
  return (
    <>
      <Seo title="Pricing" description="Starter, Professional and Enterprise plans with included reports, seats and transparent overage pricing." path="/pricing" />
      <PageHero eyebrow="Pricing" title="Plans that match your caseload" intro="Pay a fixed monthly price with a generous report allowance. If you go over, you pay a known price per extra report." />
      <Section>
        <h2 className="sr-only">Plans</h2>
        <PricingCards />
      </Section>
      <Section tone="muted" eyebrow="Compare" title="Plan comparison">
        <Comparison />
      </Section>
      <Section eyebrow="Add-ons" title="Add what you need as you grow">
        <ul className="grid max-w-3xl gap-4 text-lg text-stone-700">
          <li>
            <strong className="text-navy">Additional seats.</strong> Add reviewers at the per-seat price shown for your plan.
          </li>
          <li>
            <strong className="text-navy">Additional reports.</strong> Billed per report beyond the monthly allowance, with no interruption to work.
          </li>
          <li>
            <strong className="text-navy">Local-only processing.</strong> Keep every step on your infrastructure.{" "}
            <Link to="/contact?topic=sales" className="font-semibold text-teal-700 underline">
              Ask us about it
            </Link>
            .
          </li>
        </ul>
      </Section>
      <Section tone="muted" eyebrow="FAQ" title="Billing questions">
        <Container className="px-0">
          <Accordion type="single" collapsible className="max-w-3xl">
            {PRICING_FAQ.map((item, i) => (
              <AccordionItem key={item.q} value={`p${i}`}>
                <AccordionTrigger>{item.q}</AccordionTrigger>
                <AccordionContent>{item.a}</AccordionContent>
              </AccordionItem>
            ))}
          </Accordion>
        </Container>
      </Section>
      <CtaBanner title="Not sure which plan fits?" text="Tell us your expected volume and we will recommend one." />
    </>
  );
}
