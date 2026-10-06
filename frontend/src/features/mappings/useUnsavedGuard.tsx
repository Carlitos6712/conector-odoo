import { useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Guards unsaved edits. The app uses a declarative router, which has no navigation blocker, so
 * in-app links are intercepted in the capture phase (before React Router sees the click) and
 * closing or reloading the tab uses `beforeunload`. Modified clicks and external links pass.
 */
export function useUnsavedGuard(dirty: boolean) {
  const navigate = useNavigate();
  const [pending, setPending] = useState<string | null>(null);

  useEffect(() => {
    if (!dirty) return;
    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    const onClick = (event: MouseEvent) => {
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
      const anchor = (event.target as Element | null)?.closest?.("a[href]");
      if (!anchor || anchor.hasAttribute("download")) return;
      const href = anchor.getAttribute("href") ?? "";
      if (!href.startsWith("/") || (anchor.getAttribute("target") ?? "_self") !== "_self") return;
      event.preventDefault();
      event.stopPropagation();
      setPending(href);
    };
    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, [dirty]);

  return {
    pending: pending !== null,
    stay: () => setPending(null),
    leave: () => {
      const to = pending;
      setPending(null);
      if (to) void navigate(to);
    },
  };
}

export function UnsavedChangesDialog({
  open,
  onStay,
  onLeave,
}: {
  open: boolean;
  onStay: () => void;
  onLeave: () => void;
}) {
  const { t } = useTranslation();
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onStay()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("mappings.unsaved.title")}</DialogTitle>
        <DialogDescription>{t("mappings.unsaved.body")}</DialogDescription>
        <DialogFooter>
          <Button variant="outline" onClick={onStay}>
            {t("mappings.unsaved.stay")}
          </Button>
          <Button variant="destructive" onClick={onLeave}>
            {t("mappings.unsaved.leave")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
