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
import { describeResourceError } from "@/features/resources/errors";
import { useDeleteResource } from "@/features/resources/hooks";

export interface ResourceRef {
  profileId: number;
  name: string;
}

/** Destructive confirmation; a 409 (resource in use) stays open and explains why. */
export function DeleteResourceDialog({
  target,
  onClose,
}: {
  target: ResourceRef | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const remove = useDeleteResource();
  const { reset } = remove;

  useEffect(() => reset(), [target, reset]);

  const failure = remove.error ? describeResourceError(remove.error, "delete") : null;

  return (
    <Dialog open={target !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("resources.delete.title")}</DialogTitle>
        <DialogDescription>
          {t("resources.delete.body", { name: target?.name ?? "" })}
        </DialogDescription>
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
            onClick={() => target && remove.mutate(target, { onSuccess: onClose })}
          >
            {t("common.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
