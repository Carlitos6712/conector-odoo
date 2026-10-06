import { useTranslation } from "react-i18next";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const { t } = useTranslation();
  const message =
    error instanceof ApiError && error.code === "network_error"
      ? t("common.networkError")
      : t("common.unexpectedError");
  return (
    <div role="alert" className="flex flex-col items-start gap-3 p-6">
      <p className="text-destructive">{message}</p>
      {onRetry && (
        <Button variant="outline" onClick={onRetry}>
          {t("common.retry")}
        </Button>
      )}
    </div>
  );
}
