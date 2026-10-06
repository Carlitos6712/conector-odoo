import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import type { PropagationReport, WriteKind } from "@/features/records/types";

export interface WriteSummary extends PropagationReport {
  kind: WriteKind;
}

/** Warnings the per-job lines do not already show (kept so none is ever dropped). */
const extraWarnings = ({ propagation, warnings }: PropagationReport): string[] => {
  const shown = new Set(
    propagation.flatMap((o) => (o.warning ? [`${o.job_name}: ${o.warning}`] : [])),
  );
  return warnings.filter((w) => !shown.has(w));
};

/**
 * What a write did beyond the targeted record: one line per bidirectional job, or an explicit
 * "nothing was propagated" so a silent no-op is never mistaken for a success on both sides.
 */
export function WriteReport({
  summary,
  onDismiss,
}: {
  summary: WriteSummary;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const { propagation } = summary;
  return (
    <div role="status" className="flex flex-col gap-2 rounded-md border p-3 text-sm">
      <div className="flex items-start justify-between gap-3">
        <p className="font-medium">{t(`records.report.${summary.kind}`)}</p>
        <Button variant="ghost" size="sm" onClick={onDismiss}>
          {t("records.report.dismiss")}
        </Button>
      </div>
      {propagation.length === 0 ? (
        <p className="text-muted-foreground">{t("records.report.none")}</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {propagation.map((o, index) => (
            <li key={`${o.job_id ?? "x"}-${index}`}>
              <span className="font-medium">{o.job_name}</span>
              {": "}
              {t(`records.report.action.${o.action}`)}
              {o.counterpart_id ? ` (#${o.counterpart_id})` : ""}
              {o.warning && <span className="block text-destructive">{o.warning}</span>}
            </li>
          ))}
        </ul>
      )}
      {extraWarnings(summary).map((w) => (
        <p key={w} className="text-destructive">
          {w}
        </p>
      ))}
    </div>
  );
}
