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
import type { Job } from "@/features/jobs/types";
import { useSyncRecords } from "@/features/records/hooks";

/** Enabled jobs that read or write this profile + resource. */
export const jobsForResource = (
  jobs: readonly Job[],
  profileId: number | null,
  resource: string,
): Job[] =>
  jobs.filter(
    (job) =>
      job.enabled &&
      [job.source, job.target].some(
        (ep) => ep.profile_id === profileId && ep.resource === resource,
      ),
  );

/** Confirms running the matching jobs for real; each started run is linked from a toast. */
export function SyncRecordsDialog({
  jobs,
  open,
  onClose,
}: {
  jobs: readonly Job[];
  open: boolean;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const sync = useSyncRecords();
  const bidirectional = jobs.some((job) => job.direction === "bidirectional");

  function run() {
    sync.mutate(jobs, {
      onSuccess: (outcomes) => {
        for (const { job, run: started, error } of outcomes) {
          if (started) {
            toast({
              tone: "success",
              message: t("jobs.run.started", { id: started.id }),
              action: { label: t("jobs.run.view"), to: `/runs/${started.id}` },
            });
          } else {
            const failure = describeJobError(error, "trigger");
            toast({
              tone: "error",
              message: `${job.name}: ${t(failure.messageKey, failure.params)}`,
            });
          }
        }
        onClose();
      },
    });
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("records.sync.title")}</DialogTitle>
        <DialogDescription>{t("records.sync.body")}</DialogDescription>
        <ul className="list-disc pl-5 text-sm">
          {jobs.map((job) => (
            <li key={job.id}>{job.name}</li>
          ))}
        </ul>
        {bidirectional && (
          <p role="note" className="text-sm text-muted-foreground">
            {t("records.sync.bidirectional")}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={sync.isPending} onClick={run}>
            {t("records.sync.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
