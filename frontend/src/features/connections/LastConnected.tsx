import { useTranslation } from "react-i18next";
import { formatRelativeTime } from "@/features/connections/relative";
import { formatDateTime } from "@/features/mappings/format";

/** Relative age ("hace 3 horas") with the absolute time as a tooltip; "Nunca" when unknown. `now` (ms) comes from the query that
 * loaded the data, so rendering stays pure. */
export function LastConnected({ iso, now }: { iso: string | null; now: number }) {
  const { t, i18n } = useTranslation();
  if (iso === null)
    return <span className="text-muted-foreground">{t("connections.active.never")}</span>;
  return (
    <time dateTime={iso} title={formatDateTime(iso)}>
      {formatRelativeTime(iso, now, i18n.language)}
    </time>
  );
}
