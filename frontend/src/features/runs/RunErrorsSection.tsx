import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment, useState } from "react";
import { useTranslation } from "react-i18next";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
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
import { ERRORS_PAGE_SIZE } from "@/features/runs/api";
import { useRunErrorPage } from "@/features/runs/hooks";
import { filterErrors, type ErrorClientFilters } from "@/features/runs/policy";
import { isActiveStatus } from "@/features/runs/summary";
import { ERROR_KINDS, type RunDetail, type RunError } from "@/features/runs/types";

const REFRESH_MS = 3000;

/** Pretty JSON of a payload the server already redacted; rendered as text, never as HTML. */
function Payload({ payload }: { payload: RunError["payload"] }) {
  return (
    <pre className="max-h-64 overflow-auto rounded-md bg-muted p-3 font-mono text-xs">
      {JSON.stringify(payload, null, 2)}
    </pre>
  );
}

export function RunErrorsSection({ run }: { run: RunDetail }) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const [onlyUnretried, setOnlyUnretried] = useState(false);
  const [filters, setFilters] = useState<ErrorClientFilters>({ kind: "", retryable: "" });
  const [open, setOpen] = useState<ReadonlySet<number>>(new Set());

  const errors = useRunErrorPage(
    run.id,
    { page, onlyUnretried },
    true,
    isActiveStatus(run.status) ? REFRESH_MS : false,
  );
  const visible = errors.data ? filterErrors(errors.data.items, filters) : [];
  const total = errors.data?.total ?? 0;
  const hasNext = errors.data ? page * ERRORS_PAGE_SIZE < total : false;
  const clientFiltered = filters.kind !== "" || filters.retryable !== "";

  const toggle = (id: number) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (!next.delete(id)) next.add(id);
      return next;
    });

  let body;
  if (errors.isPending) body = <Loading />;
  else if (errors.isError)
    body = <ErrorState error={errors.error} onRetry={() => void errors.refetch()} />;
  else if (errors.data.items.length === 0)
    body = <EmptyState message={t("runs.detail.errors.none")} />;
  else if (visible.length === 0)
    body = <EmptyState message={t("runs.detail.errors.noneFiltered")} />;
  else
    body = (
      <Table>
        <caption className="sr-only">{t("runs.detail.errors.title")}</caption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("runs.detail.errors.columns.side")}</TableHead>
            <TableHead>{t("runs.detail.errors.columns.kind")}</TableHead>
            <TableHead>{t("runs.detail.errors.columns.retryable")}</TableHead>
            <TableHead>{t("runs.detail.errors.columns.record")}</TableHead>
            <TableHead>{t("runs.detail.errors.columns.message")}</TableHead>
            <TableHead>
              <span className="sr-only">{t("runs.detail.errors.columns.data")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((error) => {
            const record = error.record_ref ?? `#${error.id}`;
            const expanded = open.has(error.id);
            const panelId = `run-error-${error.id}-data`;
            return (
              <Fragment key={error.id}>
                <TableRow>
                  <TableCell>
                    {t(`runs.detail.errors.side.${error.side}`, { defaultValue: error.side })}
                  </TableCell>
                  <TableCell>
                    <Badge variant={error.kind === "conflict" ? "secondary" : "outline"}>
                      {t(`runs.detail.errors.kinds.${error.kind}`, { defaultValue: error.kind })}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {error.retryable ? t("common.yes") : t("common.no")}
                    {error.retried && (
                      <Badge variant="success" className="ml-2">
                        {t("runs.detail.errors.retried")}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="font-mono text-xs">{record}</TableCell>
                  <TableCell className="max-w-md whitespace-pre-wrap break-words">
                    {error.message}
                  </TableCell>
                  <TableCell>
                    {error.payload !== null && (
                      <Button
                        variant="ghost"
                        size="icon"
                        aria-expanded={expanded}
                        aria-controls={panelId}
                        aria-label={t(
                          expanded ? "runs.detail.errors.hideData" : "runs.detail.errors.showData",
                          { record },
                        )}
                        onClick={() => toggle(error.id)}
                      >
                        {expanded ? (
                          <ChevronDown aria-hidden className="size-4" />
                        ) : (
                          <ChevronRight aria-hidden className="size-4" />
                        )}
                      </Button>
                    )}
                  </TableCell>
                </TableRow>
                {expanded && (
                  <TableRow id={panelId}>
                    <TableCell colSpan={6}>
                      <Payload payload={error.payload} />
                    </TableCell>
                  </TableRow>
                )}
              </Fragment>
            );
          })}
        </TableBody>
      </Table>
    );

  return (
    <section aria-labelledby="run-errors-title" className="flex flex-col gap-3">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2 id="run-errors-title" className="text-lg font-semibold">
          {t("runs.detail.errors.title")}
        </h2>
        {errors.data && (
          <p className="text-sm text-muted-foreground">
            {t("runs.detail.errors.count", { count: total })}
          </p>
        )}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1">
          <Label htmlFor="run-errors-kind">{t("runs.detail.errors.filterKind")}</Label>
          <Select
            id="run-errors-kind"
            value={filters.kind}
            onChange={(e) => setFilters({ ...filters, kind: e.target.value })}
          >
            <option value="">{t("runs.detail.errors.all")}</option>
            {ERROR_KINDS.map((kind) => (
              <option key={kind} value={kind}>
                {t(`runs.detail.errors.kinds.${kind}`)}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex flex-col gap-1">
          <Label htmlFor="run-errors-retryable">{t("runs.detail.errors.filterRetryable")}</Label>
          <Select
            id="run-errors-retryable"
            value={filters.retryable}
            onChange={(e) =>
              setFilters({
                ...filters,
                retryable: e.target.value as ErrorClientFilters["retryable"],
              })
            }
          >
            <option value="">{t("runs.detail.errors.all")}</option>
            <option value="yes">{t("common.yes")}</option>
            <option value="no">{t("common.no")}</option>
          </Select>
        </div>
        <div className="flex items-center gap-2 pb-2">
          <Checkbox
            id="run-errors-pending"
            checked={onlyUnretried}
            onChange={(event) => {
              setOnlyUnretried(event.target.checked);
              setPage(1);
            }}
          />
          <Label htmlFor="run-errors-pending">{t("runs.detail.errors.onlyPending")}</Label>
        </div>
        {run.counters.conflicts > 0 && (
          <Button
            type="button"
            variant="outline"
            onClick={() => setFilters({ ...filters, kind: "conflict" })}
          >
            {t("runs.detail.errors.viewConflicts")}
          </Button>
        )}
      </div>
      {clientFiltered && (
        <p className="text-sm text-muted-foreground">{t("runs.detail.errors.clientNote")}</p>
      )}
      {body}
      {errors.data && (page > 1 || hasNext) && (
        <Pagination page={page} hasNext={hasNext} onPageChange={setPage} />
      )}
    </section>
  );
}
