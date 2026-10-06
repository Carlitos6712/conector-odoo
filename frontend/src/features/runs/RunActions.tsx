import { Ban, Play, RotateCcw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { AdminOnly } from "@/auth/AdminOnly";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import type { RunActionName } from "@/features/runs/api";
import { describeRunError } from "@/features/runs/errors";
import { useRunAction } from "@/features/runs/hooks";
import { canCancel, canResume, canRetryFailed } from "@/features/runs/policy";
import type { Run } from "@/features/runs/types";

const ICONS = { cancel: Ban, resume: Play, retryFailed: RotateCcw } as const;
const BODY_KEY = { cancel: "cancelBody", resume: "resumeBody", retryFailed: "retryBody" } as const;

/**
 * Cancel, resume and retry-failed for one run, admin only. Every action asks first; a refusal
 * (409, 404, 429) stays inside the dialog, success is a toast and a refresh of the run queries.
 */
export function RunActions({ run, now }: { run: Run; now: number }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const mutation = useRunAction();
  const [pending, setPending] = useState<RunActionName | null>(null);

  const available: RunActionName[] = [];
  if (canCancel(run)) available.push("cancel");
  if (canResume(run, now)) available.push("resume");
  if (canRetryFailed(run)) available.push("retryFailed");

  const close = () => {
    setPending(null);
    mutation.reset();
  };
  const confirm = () => {
    if (!pending) return;
    const action = pending;
    mutation.mutate(
      { id: run.id, action },
      {
        onSuccess: (result) => {
          toast({
            tone: "success",
            message: t(
              action === "cancel"
                ? "runs.detail.actions.cancelled"
                : action === "resume"
                  ? "runs.detail.actions.resumed"
                  : "runs.detail.actions.retried",
              { id: result.id },
            ),
            action:
              action === "retryFailed"
                ? { label: t("runs.detail.view"), to: `/runs/${result.id}` }
                : undefined,
          });
          close();
        },
      },
    );
  };

  const failure = mutation.error && pending ? describeRunError(mutation.error, pending) : null;

  return (
    <AdminOnly>
      <div className="flex flex-wrap gap-2">
        {available.map((action) => {
          const Icon = ICONS[action];
          return (
            <Button key={action} variant="outline" onClick={() => setPending(action)}>
              <Icon aria-hidden className="size-4" />
              {t(`runs.detail.actions.${action}`)}
            </Button>
          );
        })}
      </div>
      <Dialog open={pending !== null} onOpenChange={(open) => !open && close()}>
        <DialogContent role="alertdialog">
          <DialogTitle>{pending ? t(`runs.detail.actions.${pending}`) : ""}</DialogTitle>
          <DialogDescription>
            {pending ? t(`runs.detail.actions.${BODY_KEY[pending]}`, { id: run.id }) : ""}
          </DialogDescription>
          {failure && (
            <p role="alert" className="text-sm text-destructive">
              {t(failure.messageKey, failure.params)}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={close}>
              {t("runs.detail.actions.back")}
            </Button>
            <Button disabled={mutation.isPending} onClick={confirm}>
              {pending ? t(`runs.detail.actions.${pending}`) : ""}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AdminOnly>
  );
}
