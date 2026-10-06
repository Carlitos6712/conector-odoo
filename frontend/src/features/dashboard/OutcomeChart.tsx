import { useId, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import type { DayBucket } from "@/features/dashboard/derive";
import { cn } from "@/lib/utils";

type Series = "succeeded" | "partial" | "failed" | "other";
/** Stack order, bottom to top. Color is never the only cue: totals and a table back it up. */
const SERIES: readonly { key: Series; swatch: string }[] = [
  { key: "succeeded", swatch: "bg-success" },
  { key: "partial", swatch: "bg-warning" },
  { key: "failed", swatch: "bg-destructive" },
  { key: "other", swatch: "bg-muted-foreground/40" },
];

const CHART_HEIGHT_PX = 120;

function dayLabel(day: string, options: Intl.DateTimeFormatOptions): string {
  const [year, month, date] = day.split("-").map(Number);
  return new Date(year ?? 0, (month ?? 1) - 1, date ?? 1).toLocaleDateString("es-ES", options);
}

/** Stacked daily counts as plain CSS bars, with a text alternative and a table fallback. */
export function OutcomeChart({ buckets }: { buckets: readonly DayBucket[] }) {
  const { t } = useTranslation();
  const [showTable, setShowTable] = useState(false);
  const tableId = useId();
  const max = Math.max(...buckets.map((b) => b.total), 1);
  const totals = SERIES.map(({ key }) => buckets.reduce((sum, b) => sum + b[key], 0));
  const total = totals.reduce((sum, n) => sum + n, 0);
  const alt = t("dashboard.chart.alt", {
    total: t("dashboard.chart.runs", { count: total }),
    breakdown: SERIES.map(({ key }, i) =>
      t(`dashboard.chart.${key}`, { count: totals[i] ?? 0 }),
    ).join(", "),
  });

  return (
    <div className="flex flex-col gap-3">
      <div role="img" aria-label={alt} className="grid grid-cols-7 gap-2">
        {buckets.map((bucket) => (
          <div key={bucket.day} aria-hidden className="flex flex-col items-center gap-1">
            <span className="text-xs tabular-nums">{bucket.total}</span>
            <div
              className="flex w-full max-w-10 flex-col-reverse overflow-hidden rounded-sm bg-muted/40"
              style={{ height: CHART_HEIGHT_PX }}
            >
              {SERIES.map(({ key, swatch }) =>
                bucket[key] > 0 ? (
                  <div
                    key={key}
                    className={swatch}
                    style={{ height: `${(bucket[key] / max) * 100}%` }}
                  />
                ) : null,
              )}
            </div>
            <span className="text-xs text-muted-foreground">
              {dayLabel(bucket.day, { weekday: "short" })}{" "}
              {dayLabel(bucket.day, { day: "numeric" })}
            </span>
          </div>
        ))}
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        {SERIES.map(({ key, swatch }) => (
          <li key={key} className="inline-flex items-center gap-1.5">
            <span aria-hidden className={cn("size-2.5 rounded-sm", swatch)} />
            {key === "other" ? t("dashboard.chart.other") : t(`runs.status.${key}`)}
          </li>
        ))}
      </ul>
      <div>
        <Button
          variant="outline"
          size="sm"
          aria-expanded={showTable}
          aria-controls={tableId}
          onClick={() => setShowTable((v) => !v)}
        >
          {t(showTable ? "dashboard.chart.hideTable" : "dashboard.chart.showTable")}
        </Button>
      </div>
      {showTable && (
        <Table id={tableId} aria-label={t("dashboard.chart.table")}>
          <TableHeader>
            <TableRow>
              <TableHead>{t("dashboard.chart.day")}</TableHead>
              {SERIES.map(({ key }) => (
                <TableHead key={key}>
                  {key === "other" ? t("dashboard.chart.other") : t(`runs.status.${key}`)}
                </TableHead>
              ))}
              <TableHead>{t("dashboard.chart.total")}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {buckets.map((bucket) => (
              <TableRow key={bucket.day}>
                <TableCell>
                  {dayLabel(bucket.day, { weekday: "long", day: "numeric", month: "short" })}
                </TableCell>
                {SERIES.map(({ key }) => (
                  <TableCell key={key}>{bucket[key]}</TableCell>
                ))}
                <TableCell className="font-medium">{bucket.total}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </div>
  );
}
