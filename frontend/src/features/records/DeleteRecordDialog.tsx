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
import { recordLabel } from "@/features/records/columns";
import { describeRecordError } from "@/features/records/errors";
import { useDeleteRecord } from "@/features/records/hooks";
import type { PropagationReport, RecordTarget, RemoteRecord } from "@/features/records/types";

/**
 * Confirmation for deleting ONE record. It names the record and the model, says the deletion is
 * permanent, and keeps the backend's refusal (e.g. "used in invoices") visible instead of closing.
 */
export function DeleteRecordDialog({
  target,
  record,
  onClose,
  onWritten,
}: {
  target: RecordTarget;
  record: RemoteRecord | null;
  onClose: () => void;
  onWritten: (report: PropagationReport) => void;
}) {
  const { t } = useTranslation();
  const remove = useDeleteRecord(target);
  const { reset } = remove;
  useEffect(() => reset(), [record, reset]);

  const failure = remove.error ? describeRecordError(remove.error, "delete") : null;

  return (
    <Dialog open={record !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("records.delete.title")}</DialogTitle>
        <DialogDescription>
          {record
            ? t("records.delete.body", {
                name: recordLabel(record),
                id: record.id,
                model: target.resource,
              })
            : ""}
        </DialogDescription>
        <p className="text-sm text-muted-foreground">{t("records.counterpart.delete")}</p>
        {failure && (
          <div role="alert" className="flex flex-col gap-1 text-sm text-destructive">
            <p>{t(failure.messageKey)}</p>
            {failure.detail && <p className="break-words">{failure.detail}</p>}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button
            variant="destructive"
            disabled={remove.isPending}
            onClick={() =>
              record &&
              remove.mutate(record.id, {
                onSuccess: (result) => {
                  onWritten(result);
                  onClose();
                },
              })
            }
          >
            {t("records.delete.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
