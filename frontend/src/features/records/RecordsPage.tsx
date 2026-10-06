import { Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSearchParams } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
import { EmptyState } from "@/components/EmptyState";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Pagination } from "@/components/ui/pagination";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useProfiles } from "@/features/connections/hooks";
import { allColumns, pickColumns, recordLabel } from "@/features/records/columns";
import { DeleteRecordDialog } from "@/features/records/DeleteRecordDialog";
import { EditRecordDialog } from "@/features/records/EditRecordDialog";
import { describeRecordError } from "@/features/records/errors";
import { useRecords } from "@/features/records/hooks";
import type { RemoteRecord } from "@/features/records/types";
import { useDebounced } from "@/features/records/useDebounced";
import { formatCell } from "@/features/resources/format";
import { useResources } from "@/features/resources/hooks";

const PAGE_SIZES = [25, 50, 100] as const;
const DEFAULT_PAGE_SIZE = 50;
const DEFAULT_MODEL = "res.partner";

const showValue = (value: unknown): string => (value === false ? "—" : formatCell(value).text);

/** Browse, edit and delete INDIVIDUAL records of an Odoo connection. No bulk actions exist. */
export function RecordsPage() {
  const { t } = useTranslation();
  const profiles = useProfiles();
  const connections = profiles.data ?? [];
  const [params] = useSearchParams();

  // The query string only seeds the first render, e.g. a link from a resource preview.
  const requestedId = Number(params.get("profile"));
  const [chosenId, setChosenId] = useState<number | null>(
    Number.isInteger(requestedId) && requestedId > 0 ? requestedId : null,
  );
  const chosen = connections.find((p) => p.id === chosenId);
  const fallback = connections.find((p) => p.type === "odoo") ?? connections[0];
  const profileId = chosen?.id ?? fallback?.id ?? null;
  // The query string seeds only the first connection; any connection change drops it.
  const [seed, setSeed] = useState(params.get("resource"));
  const [modelDraft, setModelDraft] = useState<string | null>(null);
  const [resourceChoice, setResourceChoice] = useState<string | null>(null);
  const [searchDraft, setSearchDraft] = useState("");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState<number>(DEFAULT_PAGE_SIZE);
  const [showAll, setShowAll] = useState(false);
  const [editing, setEditing] = useState<RemoteRecord | null>(null);
  const [deleting, setDeleting] = useState<RemoteRecord | null>(null);

  const isRest = (chosen ?? fallback)?.type === "rest";
  const resources = useResources(isRest ? profileId : null);
  const resourceNames = (resources.data?.items ?? []).map((r) => r.config.name);
  const restResource =
    [resourceChoice, seed].find((n) => n && resourceNames.includes(n)) ?? resourceNames[0] ?? "";
  const debouncedModel = useDebounced((modelDraft ?? seed ?? DEFAULT_MODEL).trim());
  const odooResource = modelDraft === null && seed === null ? DEFAULT_MODEL : debouncedModel;
  const resource = isRest ? restResource : odooResource;
  const search = useDebounced(searchDraft.trim());
  const target = { profileId: profileId ?? -1, resource };
  const records = useRecords(
    profileId !== null && resource
      ? { ...target, search, limit: pageSize, offset: (page - 1) * pageSize }
      : null,
  );

  if (profiles.isPending) return <Loading />;

  const data = records.data;
  const columns = data
    ? showAll
      ? allColumns(data.schema, data.items)
      : pickColumns(data.schema)
    : [];
  const failure = records.isError ? describeRecordError(records.error, "load") : null;

  return (
    <div className="flex flex-col gap-6">
      <header>
        <h1 className="text-2xl font-semibold">{t("records.title")}</h1>
        <p className="text-sm text-muted-foreground">{t("records.intro")}</p>
      </header>

      {connections.length === 0 ? (
        <EmptyState message={t("records.noProfiles")} />
      ) : (
        <>
          <div className="grid gap-4 sm:grid-cols-4">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="records-profile">{t("records.connection")}</Label>
              <Select
                id="records-profile"
                value={profileId ?? ""}
                onChange={(e) => {
                  setChosenId(Number(e.target.value));
                  setSeed(null);
                  setModelDraft(null);
                  setResourceChoice(null);
                  setPage(1);
                }}
              >
                {connections.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="records-model">
                {t(isRest ? "records.resource" : "records.model")}
              </Label>
              {isRest ? (
                <Select
                  id="records-model"
                  value={restResource}
                  onChange={(e) => {
                    setResourceChoice(e.target.value);
                    setPage(1);
                  }}
                >
                  {resourceNames.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  id="records-model"
                  value={modelDraft ?? seed ?? DEFAULT_MODEL}
                  spellCheck={false}
                  onChange={(e) => {
                    setModelDraft(e.target.value);
                    setPage(1);
                  }}
                />
              )}
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="records-search">{t("records.search")}</Label>
              <Input
                id="records-search"
                type="search"
                maxLength={200}
                value={searchDraft}
                onChange={(e) => {
                  setSearchDraft(e.target.value);
                  setPage(1);
                }}
              />
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="records-page-size">{t("records.pageSize")}</Label>
              <Select
                id="records-page-size"
                value={pageSize}
                onChange={(e) => {
                  setPageSize(Number(e.target.value));
                  setPage(1);
                }}
              >
                {PAGE_SIZES.map((n) => (
                  <option key={n} value={n}>
                    {n}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {failure ? (
            <div role="alert" className="flex flex-col items-start gap-2 text-sm">
              <p className="text-destructive">{t(failure.messageKey)}</p>
              {failure.detail && (
                <p className="break-words text-muted-foreground">{failure.detail}</p>
              )}
              <Button variant="outline" size="sm" onClick={() => void records.refetch()}>
                {t("common.retry")}
              </Button>
            </div>
          ) : !data ? (
            resource ? (
              <Loading />
            ) : (
              <EmptyState message={t("records.modelRequired")} />
            )
          ) : data.items.length === 0 ? (
            <EmptyState message={t("records.empty")} />
          ) : (
            <>
              <div className="flex items-center justify-between gap-3 text-sm text-muted-foreground">
                <span>
                  {t("records.range", {
                    from: (page - 1) * pageSize + 1,
                    to: (page - 1) * pageSize + data.items.length,
                  })}
                </span>
                <Button
                  variant="outline"
                  size="sm"
                  aria-pressed={showAll}
                  onClick={() => setShowAll((v) => !v)}
                >
                  {t("records.showAllColumns")}
                </Button>
              </div>
              <Table aria-label={t("records.title")}>
                <TableHeader>
                  <TableRow>
                    <TableHead>{t("records.id")}</TableHead>
                    {columns.map((c) => (
                      <TableHead key={c.name}>{c.label ?? c.name}</TableHead>
                    ))}
                    <AdminOnly>
                      <TableHead className="text-right">{t("records.actions")}</TableHead>
                    </AdminOnly>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.items.map((record) => {
                    const label = recordLabel(record);
                    return (
                      <TableRow key={String(record.id)}>
                        <TableCell className="font-mono text-xs">{record.id}</TableCell>
                        {columns.map((c) => (
                          <TableCell key={c.name}>{showValue(record.fields[c.name])}</TableCell>
                        ))}
                        <AdminOnly>
                          <TableCell className="text-right">
                            <div className="flex justify-end gap-1">
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={t("records.editRow", { name: label })}
                                onClick={() => setEditing(record)}
                              >
                                <Pencil aria-hidden className="size-4" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="sm"
                                aria-label={t("records.deleteRow", { name: label })}
                                onClick={() => setDeleting(record)}
                              >
                                <Trash2 aria-hidden className="size-4" />
                              </Button>
                            </div>
                          </TableCell>
                        </AdminOnly>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Pagination page={page} hasNext={data.has_more} onPageChange={setPage} />
            </>
          )}

          {data && (
            <>
              <EditRecordDialog
                target={target}
                schema={data.schema}
                record={editing}
                onClose={() => setEditing(null)}
              />
              <DeleteRecordDialog
                target={target}
                record={deleting}
                onClose={() => setDeleting(null)}
              />
            </>
          )}
        </>
      )}
    </div>
  );
}
