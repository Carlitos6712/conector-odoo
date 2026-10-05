import { useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { useToast } from "@/components/ui/toast";
import { describeJobError } from "@/features/jobs/errors";
import { useTriggerRun } from "@/features/jobs/hooks";
import type { Job } from "@/features/jobs/types";

/**
 * Confirms a real run. The API answers 202 with the queued run at once, so success is a toast
 * linking to it; a 409 (already running) or 404 (job gone) stays in the dialog.
 */
export function RunNowDialog({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const trigger = useTriggerRun();
  const { reset } = trigger;
  const id = job?.id;

  useEffect(() => reset(), [id, reset]);

  const failure = trigger.error ? describeJobError(trigger.error, "trigger") : null;

  function run() {
    if (!job) return;
    trigger.mutate(
      { jobId: job.id, dryRun: false },
      {
        onSuccess: (started) => {
          toast({
            tone: "success",
            message: t("jobs.run.started", { id: started.id }),
            action: { label: t("jobs.run.view"), to: `/runs/${started.id}` },
          });
          onClose();
        },
      },
    );
  }

  return (
    <Dialog open={job !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("jobs.run.title")}</DialogTitle>
        <DialogDescription>{t("jobs.run.body", { name: job?.name ?? "" })}</DialogDescription>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {t(failure.messageKey, failure.params)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={trigger.isPending} onClick={run}>
            {t("jobs.run.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
