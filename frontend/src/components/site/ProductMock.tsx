import type { ReactNode } from "react";

import { Badge } from "@/components/ui/card";
import { cn } from "@/lib/utils";

/** A browser-style frame drawn in CSS. The content inside is a stand-in for real application screenshots. */
export function DeviceFrame({ title, children, className }: { title: string; children: ReactNode; className?: string }) {
  return (
    <div className={cn("overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-card", className)}>
      <div className="flex items-center gap-2 border-b border-stone-200 bg-stone-100 px-4 py-2.5" aria-hidden="true">
        <span className="h-2.5 w-2.5 rounded-full bg-stone-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-stone-300" />
        <span className="h-2.5 w-2.5 rounded-full bg-stone-300" />
        <span className="ml-3 truncate rounded-md bg-white px-3 py-0.5 text-xs text-stone-600">{title}</span>
      </div>
      {children}
    </div>
  );
}

const RATING = {
  Disclosed: "high",
  Partial: "medium",
  Absent: "low",
} as const;

const ROWS = [
  { n: "1", el: "a temperature sensor coupled to a battery cell", a: "Disclosed", b: "Partial", q: "a thermistor attached to the surface of each cell" },
  { n: "2", el: "a controller adjusting charge current from the reading", a: "Disclosed", b: "Absent", q: "the controller reduces charging current when the temperature exceeds a threshold" },
  { n: "3", el: "a coolant loop adjacent to the cell housing", a: "Partial", b: "Absent", q: "liquid channels run along the module wall" },
];

/** A static claim chart used on the Home and Platform pages. Labelled as a sample wherever it appears. */
export function ClaimChartMock({ compact = false }: { compact?: boolean }) {
  return (
    <DeviceFrame title="priorart-atlas.example / cases / battery-thermal-management / chart">
      <div className="p-4 sm:p-5">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <p className="text-sm font-semibold text-navy">Claim chart: sample case</p>
          <Badge tone="teal">Sample content</Badge>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[34rem] border-collapse text-left text-sm">
            <caption className="sr-only">Claim elements compared with two references</caption>
            <thead>
              <tr className="border-b border-stone-200 text-stone-600">
                <th scope="col" className="py-2 pr-3 font-medium">
                  Element
                </th>
                <th scope="col" className="px-3 py-2 font-mono font-medium">
                  US10234567B2
                </th>
                <th scope="col" className="px-3 py-2 font-mono font-medium">
                  US9876543B2
                </th>
              </tr>
            </thead>
            <tbody>
              {(compact ? ROWS.slice(0, 2) : ROWS).map((row) => (
                <tr key={row.n} className="border-b border-stone-100 align-top">
                  <th scope="row" className="py-2.5 pr-3 font-normal text-navy">
                    <span className="mr-1 font-semibold">{row.n}.</span>
                    {row.el}
                  </th>
                  <td className="px-3 py-2.5">
                    <Badge tone={RATING[row.a as keyof typeof RATING]}>{row.a}</Badge>
                    <p className="mt-1.5 font-mono text-xs text-stone-600">&ldquo;{row.q}&rdquo;</p>
                  </td>
                  <td className="px-3 py-2.5">
                    <Badge tone={RATING[row.b as keyof typeof RATING]}>{row.b}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </DeviceFrame>
  );
}

export function TourPanel({ title, rows }: { title: string; rows: string[] }) {
  return (
    <DeviceFrame title={`priorart-atlas.example / ${title.toLowerCase().replace(/\s+/g, "-")}`}>
      <div className="space-y-2 p-5">
        <div className="mb-2 flex items-center justify-between">
          <p className="text-sm font-semibold text-navy">{title}</p>
          <Badge tone="teal">Sample content</Badge>
        </div>
        {rows.map((row) => (
          <p key={row} className="rounded-lg border border-stone-200 bg-stone-50 px-3 py-3 font-mono text-xs text-navy sm:text-sm">
            {row}
          </p>
        ))}
      </div>
    </DeviceFrame>
  );
}
