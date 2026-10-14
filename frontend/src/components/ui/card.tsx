import * as React from "react";

import { cn } from "@/lib/utils";

export const Card = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} className={cn("rounded-2xl border border-stone-200 bg-white shadow-card", className)} {...props} />
  ),
);
Card.displayName = "Card";

export const CardContent = ({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) => (
  <div className={cn("p-6", className)} {...props} />
);

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div aria-hidden="true" className={cn("animate-pulse rounded-md bg-stone-200", className)} {...props} />;
}

type BadgeTone = "neutral" | "high" | "medium" | "low" | "teal" | "navy";
const tones: Record<BadgeTone, string> = {
  neutral: "bg-stone-100 text-stone-700",
  high: "bg-red-50 text-risk-high ring-1 ring-inset ring-red-200",
  medium: "bg-amber-50 text-risk-medium ring-1 ring-inset ring-amber-200",
  low: "bg-green-50 text-risk-low ring-1 ring-inset ring-green-200",
  teal: "bg-teal-50 text-teal-800 ring-1 ring-inset ring-teal-200",
  navy: "bg-navy text-white",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: React.HTMLAttributes<HTMLSpanElement> & { tone?: BadgeTone }) {
  return (
    <span
      className={cn("inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-sm font-medium", tones[tone], className)}
      {...props}
    />
  );
}
