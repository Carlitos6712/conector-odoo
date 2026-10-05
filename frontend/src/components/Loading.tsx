import { Loader2 } from "lucide-react";
import { useTranslation } from "react-i18next";

export function Loading() {
  const { t } = useTranslation();
  return (
    <div role="status" className="flex items-center gap-2 p-6 text-muted-foreground">
      <Loader2 aria-hidden className="size-4 animate-spin" />
      <span>{t("common.loading")}</span>
    </div>
  );
}
