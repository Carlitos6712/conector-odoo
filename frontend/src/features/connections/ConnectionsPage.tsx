import { Pencil, Plus, Trash2, Zap } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
import { useSession } from "@/auth/useSession";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { DeleteProfileDialog } from "@/features/connections/DeleteProfileDialog";
import { useProfiles, useTestSaved } from "@/features/connections/hooks";
import type { ConnectionTestResult, Profile } from "@/features/connections/types";

type Outcome = ConnectionTestResult | "error";

function TestBadge({ outcome }: { outcome: Outcome | undefined }) {
  const { t } = useTranslation();
  if (outcome === undefined) return <Badge>{t("connections.status.untested")}</Badge>;
  if (outcome === "error")
    return <Badge variant="destructive">{t("connections.status.error")}</Badge>;
  if (outcome.ok) return <Badge variant="success">{t("connections.status.ok")}</Badge>;
  const step = outcome.failed_step ?? "";
  return (
    <Badge variant="destructive">
      {t("connections.status.failedAt", {
        step: t(`connections.steps.${step}`, { defaultValue: step }),
      })}
    </Badge>
  );
}

export function ConnectionsPage() {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const profiles = useProfiles();
  const testSaved = useTestSaved();
  const [outcomes, setOutcomes] = useState<Record<number, Outcome>>({});
  const [testingId, setTestingId] = useState<number | null>(null);
  const [toDelete, setToDelete] = useState<Profile | null>(null);

  function runTest(id: number) {
    setTestingId(id);
    testSaved.mutate(id, {
      onSuccess: (result) => setOutcomes((prev) => ({ ...prev, [id]: result })),
      onError: () => setOutcomes((prev) => ({ ...prev, [id]: "error" })),
      onSettled: () => setTestingId(null),
    });
  }

  const newLink = (
    <Button asChild>
      <Link to="/connections/new">
        <Plus aria-hidden className="size-4" />
        {t("connections.new")}
      </Link>
    </Button>
  );

  let body;
  if (profiles.isPending) body = <Loading />;
  else if (profiles.isError)
    body = <ErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />;
  else if (profiles.data.length === 0)
    body = (
      <EmptyState
        message={t(canMutate ? "connections.empty" : "connections.emptyReadOnly")}
        action={<AdminOnly>{newLink}</AdminOnly>}
      />
    );
  else
    body = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("connections.columns.name")}</TableHead>
            <TableHead>{t("connections.columns.kind")}</TableHead>
            <TableHead>{t("connections.columns.baseUrl")}</TableHead>
            <TableHead>{t("connections.columns.status")}</TableHead>
            <AdminOnly>
              <TableHead>
                <span className="sr-only">{t("connections.columns.actions")}</span>
              </TableHead>
            </AdminOnly>
          </TableRow>
        </TableHeader>
        <TableBody>
          {profiles.data.map((profile) => (
            <TableRow key={profile.id}>
              <TableCell className="font-medium">{profile.name}</TableCell>
              <TableCell>{t(`connections.kinds.${profile.type}`)}</TableCell>
              <TableCell className="break-all">{profile.base_url}</TableCell>
              <TableCell>
                <TestBadge outcome={outcomes[profile.id]} />
              </TableCell>
              <AdminOnly>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      disabled={testingId === profile.id}
                      aria-label={t("connections.actions.test", { name: profile.name })}
                      onClick={() => runTest(profile.id)}
                    >
                      <Zap aria-hidden className="size-4" />
                    </Button>
                    <Button variant="ghost" size="icon" asChild>
                      <Link
                        to={`/connections/${profile.id}/edit`}
                        aria-label={t("connections.actions.edit", { name: profile.name })}
                      >
                        <Pencil aria-hidden className="size-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("connections.actions.delete", { name: profile.name })}
                      onClick={() => setToDelete(profile)}
                    >
                      <Trash2 aria-hidden className="size-4" />
                    </Button>
                  </div>
                </TableCell>
              </AdminOnly>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("nav.connections")}</h1>
        {profiles.data && profiles.data.length > 0 && <AdminOnly>{newLink}</AdminOnly>}
      </div>
      {body}
      <DeleteProfileDialog profile={toDelete} onClose={() => setToDelete(null)} />
    </section>
  );
}
