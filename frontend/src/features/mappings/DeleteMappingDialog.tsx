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
import { describeMappingError } from "@/features/mappings/errors";
import { useDeleteMapping } from "@/features/mappings/hooks";

/** Destructive confirmation; a 409 (a job uses some version) stays open and explains why. */
export function DeleteMappingDialog({
  name,
  onClose,
}: {
  name: string | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const remove = useDeleteMapping();
  const { reset } = remove;

  useEffect(() => reset(), [name, reset]);

  const failure = remove.error ? describeMappingError(remove.error, "delete") : null;

  return (
    <Dialog open={name !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("mappings.delete.title")}</DialogTitle>
        <DialogDescription>{t("mappings.delete.body", { name: name ?? "" })}</DialogDescription>
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
            onClick={() => name && remove.mutate(name, { onSuccess: onClose })}
          >
            {t("common.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
