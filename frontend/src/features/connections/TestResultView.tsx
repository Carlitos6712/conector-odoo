import { CheckCircle2, XCircle } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import type { ConnectionTestResult } from "@/features/connections/types";

/** Probe steps in order; the failing one is highlighted with its (server-masked) message. */
export function TestResultView({ result }: { result: ConnectionTestResult }) {
  const { t } = useTranslation();
  const stepLabel = (name: string) => t(`connections.steps.${name}`, { defaultValue: name });
  return (
    <div className="flex flex-col gap-3">
      {result.ok && (
        <p role="status" className="font-medium text-emerald-700 dark:text-emerald-400">
          {t("connections.status.ok")}
        </p>
      )}
      <ol className="flex flex-col gap-2">
        {result.steps.map((step) => (
          <li
            key={step.name}
            data-step={step.name}
            data-state={step.ok ? "ok" : "failed"}
            className={cn(
              "flex items-start gap-2 rounded-md border p-3 text-sm",
              !step.ok && "border-destructive bg-destructive/10",
            )}
          >
            {step.ok ? (
              <CheckCircle2 aria-hidden className="mt-0.5 size-4 text-emerald-600" />
            ) : (
              <XCircle aria-hidden className="mt-0.5 size-4 text-destructive" />
            )}
            <div className="flex flex-col gap-1">
              {step.ok ? (
                <>
                  <span className="font-medium">
                    {stepLabel(step.name)}
                    <span className="sr-only"> {t("connections.test.passed")}</span>
                  </span>
                  <span className="text-muted-foreground">{step.detail}</span>
                </>
              ) : (
                <div role="alert" className="flex flex-col gap-1">
                  <span className="font-medium">
                    {t("connections.test.failedAt", { step: stepLabel(step.name) })}
                  </span>
                  <span>{step.detail}</span>
                  {step.hint && (
                    <span className="text-muted-foreground">
                      {t("connections.test.hint", { hint: step.hint })}
                    </span>
                  )}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  );
}
