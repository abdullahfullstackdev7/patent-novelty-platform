import { Check } from "lucide-react";
import { Link } from "react-router-dom";

import { Button } from "@/components/ui/button";
import { Badge, Card, CardContent, Skeleton } from "@/components/ui/card";
import { usePlans } from "@/lib/queries";
import type { Plan } from "@/lib/api";
import { formatMoney } from "@/lib/utils";

export function planFeatures(plan: Plan): string[] {
  return [
    `${plan.included_reports} novelty reports per month included`,
    `${plan.seats} user seats included`,
    `Additional reports ${formatMoney(plan.overage_price)} each`,
    plan.extra_seat_price > 0 ? `Additional seats ${formatMoney(plan.extra_seat_price)} per month` : "Seats included in the price",
  ];
}

export function PricingCards() {
  const plans = usePlans();

  if (plans.isError) {
    return (
      <p role="alert" className="rounded-xl border border-stone-200 bg-stone-50 p-6 text-base text-stone-700">
        Pricing could not be loaded right now. Please{" "}
        <Link to="/contact?topic=sales" className="font-semibold text-teal-700 underline">
          contact sales
        </Link>{" "}
        for a quote.
      </p>
    );
  }

  if (!plans.data) {
    return (
      <div className="grid gap-6 md:grid-cols-3" aria-busy="true" aria-label="Loading pricing">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-72" />
        ))}
      </div>
    );
  }

  const featured = plans.data.length === 3 ? plans.data[1].code : null;
  return (
    <div className="grid gap-6 md:grid-cols-3">
      {plans.data.map((plan) => (
        <Card key={plan.code} className={plan.code === featured ? "border-teal-600 ring-1 ring-teal-600" : ""}>
          <CardContent className="flex h-full flex-col">
            <div className="flex items-center justify-between">
              <h3 className="text-xl">{plan.name}</h3>
              {plan.code === featured && <Badge tone="teal">Most popular</Badge>}
            </div>
            <p className="mt-4">
              <span className="text-3xl font-semibold text-navy">{formatMoney(plan.monthly_price)}</span>
              <span className="text-stone-600"> / month</span>
            </p>
            <ul className="mt-5 flex-1 space-y-3 text-base text-stone-700">
              {planFeatures(plan).map((f) => (
                <li key={f} className="flex gap-2">
                  <Check className="mt-1 h-4 w-4 shrink-0 text-teal-700" aria-hidden="true" />
                  {f}
                </li>
              ))}
            </ul>
            <Button asChild variant={plan.code === featured ? "primary" : "outline"} className="mt-6">
              <Link to={`/contact?topic=sales&plan=${plan.code}`}>Talk to sales about {plan.name}</Link>
            </Button>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
