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
import { describeProfileError } from "@/features/connections/errors";
import { useDeleteProfile } from "@/features/connections/hooks";
import type { Profile } from "@/features/connections/types";

/** Destructive confirmation; a 409 (profile in use) stays open and explains why. */
export function DeleteProfileDialog({
  profile,
  onClose,
}: {
  profile: Profile | null;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const remove = useDeleteProfile();
  const { reset } = remove;

  useEffect(() => reset(), [profile, reset]);

  const failure = remove.error ? describeProfileError(remove.error, "delete") : null;

  return (
    <Dialog open={profile !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("connections.delete.title")}</DialogTitle>
        <DialogDescription>
          {t("connections.delete.body", { name: profile?.name ?? "" })}
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
            onClick={() => profile && remove.mutate(profile.id, { onSuccess: onClose })}
          >
            {t("common.delete")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
