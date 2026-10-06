import { Eye, History, Pencil, Plus, Trash2 } from "lucide-react";
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
import { DeleteMappingDialog } from "@/features/mappings/DeleteMappingDialog";
import { formatDateTime } from "@/features/mappings/format";
import { useMappings } from "@/features/mappings/hooks";

export function MappingsPage() {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const mappings = useMappings();
  const [toDelete, setToDelete] = useState<string | null>(null);

  const create = (
    <AdminOnly>
      <Button asChild>
        <Link to="/mappings/new">
          <Plus aria-hidden className="size-4" />
          {t("mappings.new")}
        </Link>
      </Button>
    </AdminOnly>
  );

  let body;
  if (mappings.isPending) body = <Loading />;
  else if (mappings.isError)
    body = <ErrorState error={mappings.error} onRetry={() => void mappings.refetch()} />;
  else if (mappings.data.length === 0)
    body = (
      <EmptyState
        message={t(canMutate ? "mappings.empty" : "mappings.emptyReadOnly")}
        action={create}
      />
    );
  else
    body = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("mappings.columns.name")}</TableHead>
            <TableHead>{t("mappings.columns.version")}</TableHead>
            <TableHead>{t("mappings.columns.source")}</TableHead>
            <TableHead>{t("mappings.columns.target")}</TableHead>
            <TableHead>{t("mappings.columns.rules")}</TableHead>
            <TableHead>{t("mappings.columns.created")}</TableHead>
            <TableHead>
              <span className="sr-only">{t("mappings.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {mappings.data.map((mapping) => {
            const { name, definition } = mapping;
            const href = `/mappings/${encodeURIComponent(name)}`;
            return (
              <TableRow key={name}>
                <TableCell className="font-mono text-xs font-medium">{name}</TableCell>
                <TableCell>
                  <Badge variant="outline">v{mapping.version}</Badge>
                </TableCell>
                <TableCell className="font-mono text-xs">{definition.source_resource}</TableCell>
                <TableCell className="font-mono text-xs">{definition.target_resource}</TableCell>
                <TableCell>{definition.rules.length}</TableCell>
                <TableCell>{formatDateTime(mapping.created_at)}</TableCell>
                <TableCell>
                  <div className="flex justify-end gap-1">
                    <Button variant="ghost" size="icon" asChild>
                      <Link
                        to={`${href}/edit`}
                        aria-label={t(
                          canMutate ? "mappings.actions.edit" : "mappings.actions.view",
                          {
                            name,
                          },
                        )}
                      >
                        {canMutate ? (
                          <Pencil aria-hidden className="size-4" />
                        ) : (
                          <Eye aria-hidden className="size-4" />
                        )}
                      </Link>
                    </Button>
                    <Button variant="ghost" size="icon" asChild>
                      <Link
                        to={`${href}/versions`}
                        aria-label={t("mappings.actions.history", { name })}
                      >
                        <History aria-hidden className="size-4" />
                      </Link>
                    </Button>
                    <AdminOnly>
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-label={t("mappings.actions.delete", { name })}
                        onClick={() => setToDelete(name)}
                      >
                        <Trash2 aria-hidden className="size-4" />
                      </Button>
                    </AdminOnly>
                  </div>
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>
    );

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("nav.mappings")}</h1>
        {mappings.data && mappings.data.length > 0 && create}
      </div>
      {body}
      <DeleteMappingDialog name={toDelete} onClose={() => setToDelete(null)} />
    </section>
  );
}
