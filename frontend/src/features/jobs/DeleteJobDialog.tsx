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
import { describeJobError } from "@/features/jobs/errors";
import { useDeleteJob } from "@/features/jobs/hooks";
import type { Job } from "@/features/jobs/types";

/** Destructive confirmation; a 409 (the job has runs) stays open and explains why. */
export function DeleteJobDialog({ job, onClose }: { job: Job | null; onClose: () => void }) {
  const { t } = useTranslation();
  const remove = useDeleteJob();
  const { reset } = remove;
  const id = job?.id;

  useEffect(() => reset(), [id, reset]);

  const failure = remove.error ? describeJobError(remove.error, "delete") : null;

  return (
    <Dialog open={job !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("jobs.delete.title")}</DialogTitle>
        <DialogDescription>{t("jobs.delete.body", { name: job?.name ?? "" })}</DialogDescription>
        {failure && (
          <p role="alert" className="text-sm text-destructive">
            {t(failure.messageKey, failure.params)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() => job && remove.mutate(job.id, { onSuccess: onClose })}
          >
            {t("common.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
