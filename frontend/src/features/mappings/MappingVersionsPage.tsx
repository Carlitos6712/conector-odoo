import { ArrowLeft } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
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
import { describeMappingError } from "@/features/mappings/errors";
import { formatDateTime } from "@/features/mappings/format";
import { useMappingVersions, useSaveMapping } from "@/features/mappings/hooks";
import { IssueList } from "@/features/mappings/IssueList";
import type { StoredMapping } from "@/features/mappings/types";

/** Read-only history; restoring stores the old definition as the next version. */
export function MappingVersionsPage() {
  const { t } = useTranslation();
  const { name = "" } = useParams();
  const versions = useMappingVersions(name);
  const save = useSaveMapping();
  const [viewing, setViewing] = useState<StoredMapping | null>(null);

  const ordered = [...(versions.data ?? [])].sort((a, b) => b.version - a.version);
  const latest = ordered[0]?.version;
  const failure = save.error ? describeMappingError(save.error, "save") : null;

  let body;
  if (versions.isPending) body = <Loading />;
  else if (versions.isError)
    body = <ErrorState error={versions.error} onRetry={() => void versions.refetch()} />;
  else if (ordered.length === 0) body = <EmptyState />;
  else
    body = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("mappings.columns.version")}</TableHead>
            <TableHead>{t("mappings.columns.created")}</TableHead>
            <TableHead>{t("mappings.columns.rules")}</TableHead>
            <TableHead>
              <span className="sr-only">{t("mappings.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {ordered.map((item) => (
            <TableRow key={item.version}>
              <TableCell>
                <span className="font-medium">v{item.version}</span>{" "}
                {item.version === latest && (
                  <Badge variant="secondary">{t("mappings.versions.latest")}</Badge>
                )}
              </TableCell>
              <TableCell>{formatDateTime(item.created_at)}</TableCell>
              <TableCell>{item.definition.rules.length}</TableCell>
              <TableCell>
                <div className="flex justify-end gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    aria-pressed={viewing?.version === item.version}
                    onClick={() => setViewing(viewing?.version === item.version ? null : item)}
                  >
                    {t("mappings.versions.view", { version: item.version })}
                  </Button>
                  {item.version !== latest && (
                    <AdminOnly>
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={save.isPending}
                        onClick={() => {
                          save.reset();
                          save.mutate({ name, definition: item.definition });
                        }}
                      >
                        {t("mappings.versions.restore", { version: item.version })}
                      </Button>
                    </AdminOnly>
                  )}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("mappings.versions.title", { name })}</h1>
        <Button variant="outline" asChild>
          <Link to="/mappings">
            <ArrowLeft aria-hidden className="size-4" />
            {t("mappings.versions.back")}
          </Link>
        </Button>
      </div>
      {save.data && (
        <p role="status" className="rounded-md border p-3 text-sm">
          {save.data.created
            ? t("mappings.versions.restored", { version: save.data.mapping.version })
            : t("mappings.versions.unchanged", { version: save.data.mapping.version })}
        </p>
      )}
      {failure && (
        <div role="alert" className="flex flex-col gap-2 rounded-md border border-destructive p-3">
          <p className="text-sm font-medium text-destructive">
            {t(failure.messageKey, failure.params)}
          </p>
          {failure.detail && <p className="break-words text-sm">{failure.detail}</p>}
          <IssueList issues={failure.issues} />
        </div>
      )}
      {body}
      {viewing && (
        <section aria-label={t("mappings.versions.definition", { version: viewing.version })}>
          <h2 className="mb-2 text-lg font-semibold">
            {t("mappings.versions.definition", { version: viewing.version })}
          </h2>
          <pre className="max-h-[32rem] overflow-auto rounded-md border bg-muted p-3 text-xs">
            {JSON.stringify(viewing.definition, null, 2)}
          </pre>
        </section>
      )}
    </section>
  );
}
