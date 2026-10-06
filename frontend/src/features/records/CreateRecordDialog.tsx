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
  buildCreate,
  creatableFields,
  emptyForm,
  parseFieldErrors,
  type FormValues,
} from "@/features/records/columns";
import { describeRecordError } from "@/features/records/errors";
import { useCreateRecord } from "@/features/records/hooks";
import { RecordFormFields } from "@/features/records/RecordFormFields";
import type { PropagationReport, RecordSchema, RecordTarget } from "@/features/records/types";

interface Props {
  target: RecordTarget;
  schema: RecordSchema;
  onClose: () => void;
  onWritten: (report: PropagationReport) => void;
}

/** Mounted only while open, so every opening starts from a blank form. */
function CreateForm({ target, schema, onClose, onWritten }: Props) {
  const { t } = useTranslation();
  const create = useCreateRecord(target);
  const specs = useMemo(() => creatableFields(schema), [schema]);
  const [form, setForm] = useState<FormValues>(() => emptyForm(specs));

  const failure = create.error ? describeRecordError(create.error, "save") : null;
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

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        create.mutate(buildCreate(specs, form), {
          onSuccess: (result) => {
            onWritten(result);
            onClose();
          },
        });
      }}
    >
      <DialogTitle>{t("records.create.title")}</DialogTitle>
      <DialogDescription>{t("records.create.intro", { model: target.resource })}</DialogDescription>
      <p className="text-sm text-muted-foreground">{t("records.counterpart.create")}</p>
      <RecordFormFields
        specs={specs}
        form={form}
        fieldErrors={fieldErrors}
        onChange={(name, value) => setForm((f) => ({ ...f, [name]: value }))}
      />
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
        <Button type="submit" disabled={create.isPending}>
          {t("records.create.save")}
        </Button>
      </DialogFooter>
    </form>
  );
}

export function CreateRecordDialog({ open, ...rest }: Props & { open: boolean }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && rest.onClose()}>
      <DialogContent>{open && <CreateForm {...rest} />}</DialogContent>
    </Dialog>
  );
}
