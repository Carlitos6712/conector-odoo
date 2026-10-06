import { useTranslation } from "react-i18next";
import { cronSentence } from "@/features/jobs/cronText";
import type { TriggerDoc } from "@/features/jobs/types";

/** One line (two for a schedule: the sentence and the raw expression) describing a trigger. */
export function TriggerSummary({ trigger }: { trigger: TriggerDoc }) {
  const { t } = useTranslation();
  if (trigger.kind === "manual") return <span>{t("jobs.trigger.manual")}</span>;
  if (trigger.kind === "webhook") {
    return <span>{t("jobs.trigger.webhook", { events: trigger.event_types.join(", ") })}</span>;
  }
  return (
    <div className="flex flex-col">
      <span>{cronSentence(t, trigger.cron) ?? trigger.cron}</span>
      <code className="font-mono text-xs text-muted-foreground">{trigger.cron}</code>
    </div>
  );
}
