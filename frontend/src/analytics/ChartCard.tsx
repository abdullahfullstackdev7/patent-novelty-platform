import { Download, Image as ImageIcon, Table2 } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState } from "react";

import { downloadCsv, type Query } from "@/analytics/data";
import { EChart, type EChartsInstance, type Option } from "@/analytics/EChart";
import { ErrorState, messageOf, useToast } from "@/app/components/feedback";
import { Button } from "@/components/ui/button";
import { Card, CardContent, Skeleton } from "@/components/ui/card";

export interface TableData {
  columns: string[];
  rows: (string | number | null)[][];
}

interface Props {
  title: string;
  description: string;
  option?: Option;
  height?: number;
  loading?: boolean;
  error?: unknown;
  onRetry?: () => void;
  empty?: boolean;
  emptyText?: string;
  csv?: { path: string; query: Query; filename: string };
  table?: TableData;
  note?: string | null;
  className?: string;
}

/** A chart with its title, a plain-language description, a table view, and CSV and PNG export. */
export function ChartCard({ title, description, option, height = 300, loading, error, onRetry, empty, emptyText = "No data for these filters.", csv, table, note, className }: Props) {
  const chart = useRef<EChartsInstance | null>(null);
  const [asTable, setAsTable] = useState(false);
  const toast = useToast();
  const queries = useQueryClient();
  const headingId = `chart-${title.replace(/\W+/g, "-").toLowerCase()}`;

  async function exportCsv() {
    if (!csv) return;
    try {
      await downloadCsv(csv.path, csv.query, csv.filename);
      toast.success("CSV exported", csv.filename);
    } catch (e) {
      toast.error("Export failed", messageOf(e));
    }
  }

  function exportPng() {
    const url = chart.current?.getDataURL({ type: "png", pixelRatio: 2, backgroundColor: document.documentElement.classList.contains("dark") ? "#101c30" : "#ffffff" });
    if (!url) return;
    const link = document.createElement("a");
    link.href = url;
    link.download = `${title.replace(/\W+/g, "_").toLowerCase()}.png`;
    link.click();
  }

  return (
    <Card className={className}>
      <CardContent className="p-5">
        <section aria-labelledby={headingId}>
          <div className="flex flex-wrap items-start justify-between gap-2">
            <div className="min-w-0">
              <h2 id={headingId} className="text-base">
                {title}
              </h2>
              <p className="mt-0.5 text-sm text-stone-700">{description}</p>
            </div>
            <div className="flex shrink-0 gap-1">
              {table && (
                <Button variant="ghost" size="sm" aria-pressed={asTable} aria-label={`${asTable ? "Show chart" : "Show table"} for ${title}`} onClick={() => setAsTable(!asTable)}>
                  <Table2 className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
              {csv && (
                <Button variant="ghost" size="sm" aria-label={`Export ${title} as CSV`} onClick={exportCsv}>
                  <Download className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
              {option && !asTable && (
                <Button variant="ghost" size="sm" aria-label={`Export ${title} as PNG`} onClick={exportPng}>
                  <ImageIcon className="h-4 w-4" aria-hidden="true" />
                </Button>
              )}
            </div>
          </div>

          <div className="mt-3">
            {error ? (
              <ErrorState error={error} onRetry={onRetry ?? (() => queries.invalidateQueries({ queryKey: ["analytics"] }))} />
            ) : empty ? (
              <p className="grid place-items-center rounded-lg border border-dashed border-stone-300 text-center text-stone-700" style={{ height }}>
                {emptyText}
              </p>
            ) : loading ? (
              <Skeleton className="w-full" style={{ height }} />
            ) : asTable && table ? (
              <div className="overflow-auto" style={{ maxHeight: height }}>
                <table className="w-full border-collapse text-left text-sm">
                  <caption className="sr-only">{title}</caption>
                  <thead>
                    <tr>
                      {table.columns.map((c) => (
                        <th key={c} scope="col" className="sticky top-0 border-b border-stone-200 bg-white px-2 py-1.5 font-semibold">
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {table.rows.map((row, i) => (
                      <tr key={i} className="border-b border-stone-100">
                        {row.map((cell, j) => (
                          <td key={j} className="px-2 py-1.5 tabular-nums">
                            {cell ?? ""}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : option ? (
              <EChart option={option} height={height} label={`${title}. ${description}`} chartRef={chart} />
            ) : null}
          </div>
          {note && <p className="mt-2 text-xs text-stone-600">{note}</p>}
        </section>
      </CardContent>
    </Card>
  );
}
