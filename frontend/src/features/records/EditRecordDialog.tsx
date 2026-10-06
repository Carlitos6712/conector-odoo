import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  buildPatch,
  editableFields,
  initialForm,
  parseFieldErrors,
  recordLabel,
  type FormValues,
} from "@/features/records/columns";
import { describeRecordError } from "@/features/records/errors";
import { useUpdateRecord } from "@/features/records/hooks";
import { RecordFormFields } from "@/features/records/RecordFormFields";
import type {
  PropagationReport,
  RecordSchema,
  RecordTarget,
  RemoteRecord,
} from "@/features/records/types";

interface Props {
  target: RecordTarget;
  schema: RecordSchema;
  record: RemoteRecord;
  onClose: () => void;
  onWritten: (report: PropagationReport) => void;
}

/** Mounted per record (keyed by the caller), so its form state never leaks between records. */
function EditForm({ target, schema, record, onClose, onWritten }: Props) {
  const { t } = useTranslation();
  const update = useUpdateRecord(target);
  const specs = useMemo(() => editableFields(schema, record), [schema, record]);
  const [form, setForm] = useState<FormValues>(() => initialForm(specs, record));
  const patch = buildPatch(specs, record, form);
  const changed = Object.keys(patch).length > 0;

  const failure = update.error ? describeRecordError(update.error, "save") : null;
  const parsed =
    failure?.validation && failure.detail
      ? parseFieldErrors(
          failure.detail,
          specs.map((s) => s.name),
        )
      : null;
  const fieldErrors = parsed?.fieldErrors ?? {};
  const general = failure && Object.keys(fieldErrors).length === 0 ? failure : null;
  const generalDetail = parsed ? parsed.general : failure?.detail;

  const set = (name: string, value: string | boolean) => setForm((f) => ({ ...f, [name]: value }));

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        if (!changed) return;
        update.mutate(
          { id: record.id, fields: patch },
          {
            onSuccess: (result) => {
              onWritten(result);
              onClose();
            },
          },
        );
      }}
    >
      <DialogTitle>{t("records.edit.title", { name: recordLabel(record) })}</DialogTitle>
      <DialogDescription>
        {t("records.edit.intro", { model: target.resource, id: record.id })}
      </DialogDescription>
      <p className="text-sm text-muted-foreground">{t("records.counterpart.edit")}</p>
      <RecordFormFields specs={specs} form={form} fieldErrors={fieldErrors} onChange={set} />
      {general && (
        <div role="alert" className="flex flex-col gap-1 text-sm text-destructive">
          <p>{t(general.messageKey)}</p>
          {generalDetail && <p className="break-words">{generalDetail}</p>}
        </div>
      )}
      <DialogFooter>
        <Button type="button" variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button type="submit" disabled={!changed || update.isPending}>
          {t("records.edit.save")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function EditRecordDialog({
  record,
  ...rest
}: Omit<Props, "record"> & { record: RemoteRecord | null }) {
  return (
    <Dialog open={record !== null} onOpenChange={(open) => !open && rest.onClose()}>
      <DialogContent>
        {record && <EditForm key={String(record.id)} record={record} {...rest} />}
      </DialogContent>
    </Dialog>
  );
}
