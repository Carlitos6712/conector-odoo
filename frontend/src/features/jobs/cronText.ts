import type { TFunction } from "i18next";
import { describeCron } from "@/features/jobs/cron";

function joinList(t: TFunction, items: readonly string[]): string {
  if (items.length <= 1) return items.join("");
  return `${items.slice(0, -1).join(", ")} ${t("jobs.cron.and")} ${items.at(-1)}`;
}

/** A schedule in words (always UTC); null when the expression is not valid. */
export function cronSentence(t: TFunction, cron: string): string | null {
  const description = describeCron(cron);
  if (description === null) return null;
  switch (description.kind) {
    case "everyMinute":
      return t("jobs.cron.describe.everyMinute");
    case "everyNMinutes":
      return t("jobs.cron.describe.everyNMinutes", { n: description.n });
    case "hourly":
      return t("jobs.cron.describe.hourly", { minute: description.minute });
    case "daily":
      return t("jobs.cron.describe.daily", { time: description.time });
    case "weekly":
      return t("jobs.cron.describe.weekly", {
        days: joinList(
          t,
          description.days.map((day) => t(`jobs.cron.weekdays.${day}`)),
        ),
        time: description.time,
      });
    default:
      return t("jobs.cron.describe.custom", { cron: cron.trim().split(/\s+/).join(" ") });
  }
}
