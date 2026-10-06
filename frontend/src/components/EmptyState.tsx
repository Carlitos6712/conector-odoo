import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";

export function EmptyState({ message, action }: { message?: string; action?: ReactNode }) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-center gap-3 rounded-xl border border-dashed border-ring/40 bg-brand-soft/40 p-10 text-center text-muted-foreground">
      <p>{message ?? t("common.empty")}</p>
      {action}
    </div>
  );
}
