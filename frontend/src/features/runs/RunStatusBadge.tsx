import { useTranslation } from "react-i18next";
import { Badge, type BadgeProps } from "@/components/ui/badge";
import type { RunStatus } from "@/features/runs/types";

const VARIANT: Record<RunStatus, BadgeProps["variant"]> = {
  queued: "secondary",
  running: "info",
  succeeded: "success",
  partial: "warning",
  failed: "destructive",
  cancelled: "outline",
};

export function RunStatusBadge({ status }: { status: RunStatus }) {
  const { t } = useTranslation();
  return <Badge variant={VARIANT[status]}>{t(`runs.status.${status}`)}</Badge>;
}
