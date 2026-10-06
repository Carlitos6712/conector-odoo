import { AlertTriangle, Info } from "lucide-react";
import { useEffect, useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
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
import { useActiveOdoo, useDisconnectOdoo } from "@/features/connections/hooks";
import { LastConnected } from "@/features/connections/LastConnected";
import type { ActiveOdoo } from "@/features/connections/types";

function Banner({
  tone,
  icon,
  children,
}: {
  tone: "danger" | "warning" | "info";
  icon: ReactNode;
  children: ReactNode;
}) {
  const styles = {
    danger: "border-destructive bg-destructive/10 text-destructive",
    warning: "border-amber-500 bg-amber-500/10",
    info: "border-border bg-muted/40",
  } as const;
  return (
    <div
      // Only the "nothing is connected" case interrupts a screen reader.
      role={tone === "danger" ? "alert" : "note"}
      className={`flex items-start gap-3 rounded-md border p-3 text-sm ${styles[tone]}`}
    >
      <span aria-hidden className="mt-0.5">
        {icon}
      </span>
      <div className="flex flex-col gap-2">{children}</div>
    </div>
  );
}

function DisconnectDialog({
  active,
  onClose,
  onDisconnected,
}: {
  active: ActiveOdoo | null;
  onClose: () => void;
  onDisconnected: () => void;
}) {
  const { t } = useTranslation();
  const { toast } = useToast();
  const disconnect = useDisconnectOdoo();
  const { reset } = disconnect;
  const id = active?.profile_id;

  useEffect(() => reset(), [id, reset]);

  const failure = disconnect.error ? describeActiveOdooError(disconnect.error) : null;

  return (
    <Dialog open={active !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent role="alertdialog">
        <DialogTitle>{t("connections.active.disconnectDialog.title")}</DialogTitle>
        <DialogDescription>
          {t("connections.active.disconnectDialog.body", { name: active?.profile_name ?? "" })}
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
            disabled={disconnect.isPending}
            onClick={() =>
              disconnect.mutate(undefined, {
                onSuccess: () => {
                  toast({
                    tone: "success",
                    message: t("connections.active.disconnectDialog.done"),
                  });
                  onDisconnected();
                  onClose();
                },
              })
            }
          >
            {t("connections.active.disconnectDialog.confirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Which Odoo the connector uses right now, where it came from and what an admin can do about
 * it. Operators see the same facts without the actions.
 */
export function ActiveOdooPanel({
  hasOdooProfiles,
  onChange,
  onDisconnected,
}: {
  /** Whether at least one Odoo profile exists to switch to. */
  hasOdooProfiles: boolean;
  /** Moves the user to the profile list so they can pick the one to use. */
  onChange: () => void;
  onDisconnected: () => void;
}) {
  const { t } = useTranslation();
  const query = useActiveOdoo();
  const [disconnecting, setDisconnecting] = useState<ActiveOdoo | null>(null);

  let body: ReactNode;
  if (query.isPending) body = <Loading />;
  else if (query.isError)
    body = <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  else {
    const active = query.data;
    const none = active.source === "none";
    const fields: [string, ReactNode][] = [];
    if (!none) {
      if (active.profile_name) fields.push(["name", active.profile_name]);
      if (active.base_url)
        fields.push(["baseUrl", <span className="break-all">{active.base_url}</span>]);
      if (active.db) fields.push(["db", active.db]);
      if (active.login) fields.push(["login", active.login]);
    }
    fields.push(["source", t(`connections.active.source.${active.source}`)]);
    fields.push([
      "status",
      <Badge key="status" variant={active.status === "active" ? "success" : "outline"}>
        {t(`connections.active.status.${active.status}`)}
      </Badge>,
    ]);
    if (!none)
      fields.push([
        "lastConnected",
        <LastConnected iso={active.last_connected_at} now={query.dataUpdatedAt} />,
      ]);

    body = (
      <div className="flex flex-col gap-3">
        {none && (
          <Banner tone="danger" icon={<AlertTriangle className="size-4" />}>
            <p className="font-medium">{t("connections.active.none")}</p>
            <AdminOnly>
              <p>{t("connections.active.noneHint")}</p>
              <div>
                {hasOdooProfiles ? (
                  <Button size="sm" onClick={onChange}>
                    {t("connections.active.chooseExisting")}
                  </Button>
                ) : (
                  <Button size="sm" asChild>
                    <Link to="/connections/new">{t("connections.active.createOdoo")}</Link>
                  </Button>
                )}
              </div>
            </AdminOnly>
          </Banner>
        )}
        {active.source === "env" && (
          <Banner tone="info" icon={<Info className="size-4" />}>
            <p>{t("connections.active.env")}</p>
          </Banner>
        )}
        {active.status === "fallback" && (
          <Banner tone="warning" icon={<AlertTriangle className="size-4" />}>
            <p>{t("connections.active.fallback")}</p>
          </Banner>
        )}
        <dl className="grid grid-cols-[max-content_1fr] gap-x-6 gap-y-1 text-sm">
          {fields.map(([key, value]) => (
            <div key={key} className="contents">
              <dt className="text-muted-foreground">{t(`connections.active.fields.${key}`)}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
        <AdminOnly>
          <div className="flex flex-wrap gap-2">
            {hasOdooProfiles && (
              <Button variant="outline" size="sm" onClick={onChange}>
                {t("connections.active.change")}
              </Button>
            )}
            {active.source === "profile" && (
              <Button variant="outline" size="sm" onClick={() => setDisconnecting(active)}>
                {t("connections.active.disconnect")}
              </Button>
            )}
          </div>
        </AdminOnly>
        <DisconnectDialog
          active={disconnecting}
          onClose={() => setDisconnecting(null)}
          onDisconnected={onDisconnected}
        />
      </div>
    );
  }

  return (
    <section
      aria-labelledby="active-odoo-title"
      className="flex flex-col gap-3 rounded-lg border p-4"
    >
      <h2 id="active-odoo-title" className="text-lg font-semibold">
        {t("connections.active.title")}
      </h2>
      {body}
    </section>
  );
}
