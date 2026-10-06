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
import { describeActiveOdooError } from "@/features/connections/errors";
import { useActivateOdoo } from "@/features/connections/hooks";
import { TestResultView } from "@/features/connections/TestResultView";
import type { Profile } from "@/features/connections/types";

/**
 * Confirms switching the live Odoo connection. The server probes the profile before swapping, so
 * a failure keeps the dialog open with the probe steps (the failing one highlighted) and the
 * previous connection untouched.
 */
export function ActivateOdooDialog({
  profile,
  onClose,
  onActivated,
}: {
  profile: Profile | null;
  onClose: () => void;
  /** Called with the profile name once the switch succeeded (for the live region). */
  onActivated: (name: string) => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const activate = useActivateOdoo();
  const { reset } = activate;
  const id = profile?.id;

  useEffect(() => reset(), [id, reset]);

  const failure = activate.error ? describeActiveOdooError(activate.error) : null;

  function confirm() {
    if (!profile) return;
    activate.mutate(profile.id, {
      onSuccess: () => {
        const message = t("connections.active.activate.done", { name: profile.name });
        toast({ tone: "success", message });
        onActivated(profile.name);
        onClose();
      },
    });
  }

  return (
    <Dialog
      open={profile !== null}
      onOpenChange={(open) => !open && !activate.isPending && onClose()}
    >
      <DialogContent role="alertdialog" className="max-h-[90vh] max-w-xl overflow-y-auto">
        <DialogTitle>{t("connections.active.activate.title")}</DialogTitle>
        <DialogDescription>
          {t("connections.active.activate.body", { name: profile?.name ?? "" })}
        </DialogDescription>
        {activate.isPending && (
          <p role="status" className="text-sm text-muted-foreground">
            {t("connections.active.activate.probing")}
          </p>
        )}
        {failure && (
          <div className="flex flex-col gap-3">
            <p role="alert" className="text-sm text-destructive">
              {t(failure.messageKey, failure.params)}
            </p>
            {failure.result && <TestResultView result={failure.result} />}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" disabled={activate.isPending} onClick={onClose}>
            {t("common.cancel")}
          </Button>
          <Button disabled={activate.isPending} onClick={confirm}>
            {t("connections.active.activate.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
