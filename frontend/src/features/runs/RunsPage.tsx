import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
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
import { useJobs } from "@/features/jobs/hooks";
import { formatDateTime } from "@/features/mappings/format";
import { formatDuration, runDurationSeconds } from "@/features/runs/format";
import { filterRuns, statusGroup, type RunClientFilters } from "@/features/runs/policy";
import { useRuns } from "@/features/runs/hooks";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import {
  RUN_STATUSES,
  RUN_TRIGGERS,
  type Run,
  type RunCounters,
  type RunStatus,
} from "@/features/runs/types";

const COUNTER_ORDER: readonly (keyof RunCounters)[] = [
  "processed",
  "created",
  "updated",
  "skipped",
  "failed",
  "conflicts",
];

/** Zero counters are noise in a table; the processed total is always shown. */
export function CounterSummary({ counters }: { counters: RunCounters }) {
  const { t } = useTranslation();
  return (
    <ul className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs">
      {COUNTER_ORDER.filter((key) => key === "processed" || counters[key] > 0).map((key) => (
        <li
          key={key}
          className={
            (key === "failed" || key === "conflicts") && counters[key] > 0
              ? "font-medium text-destructive"
              : undefined
          }
        >
          {t(`runs.counters.${key}`, { count: counters[key] })}
        </li>
      ))}
    </ul>
  );
}

const asStatus = (value: string | null): RunStatus | "" =>
  RUN_STATUSES.find((s) => s === value) ?? "";
const asPage = (value: string | null): number => {
  const page = Number(value);
  return Number.isInteger(page) && page >= 1 ? page : 1;
};
const asJobId = (value: string | null): number | null => {
  const id = Number(value);
  return value !== null && Number.isInteger(id) && id > 0 ? id : null;
};

export function RunsPage() {
  const { t } = useTranslation();
  const [params, setParams] = useSearchParams();
  const jobId = asJobId(params.get("job"));
  const status = asStatus(params.get("status"));
  const page = asPage(params.get("page"));
  const client: RunClientFilters = {
    trigger: RUN_TRIGGERS.find((tr) => tr === params.get("trigger")) ?? "",
    dryRun:
      params.get("dry") === "yes" || params.get("dry") === "no"
        ? (params.get("dry") as "yes" | "no")
        : "",
  };

  const jobs = useJobs();
  const runs = useRuns({ jobId, status: status || null }, page);
  // Elapsed time of running rows is measured at the last refresh of the list.
  const now = runs.dataUpdatedAt;

  const update = (changes: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(changes)) {
      if (value) next.set(key, value);
      else next.delete(key);
    }
    // Any filter change starts again from the first page.
    if (!("page" in changes)) next.delete("page");
    setParams(next, { replace: true });
  };

  const jobName = (run: Run) =>
    jobs.data?.find((job) => job.id === run.job_id)?.name ??
    t("runs.unknownJob", { id: run.job_id });
  const filtered = Boolean(jobId || status || client.trigger || client.dryRun);

  const visible = runs.data ? filterRuns(runs.data.items, client) : [];
  const active = visible.filter((run) => statusGroup(run.status) === "active").length;

  const filters = (
    <form
      aria-label={t("runs.list.filters.label")}
      className="flex flex-wrap items-end gap-3"
      onSubmit={(event) => event.preventDefault()}
    >
      <div className="flex flex-col gap-1">
        <Label htmlFor="runs-filter-job">{t("runs.list.filters.job")}</Label>
        <Select
          id="runs-filter-job"
          value={jobId?.toString() ?? ""}
          onChange={(e) => update({ job: e.target.value })}
        >
          <option value="">{t("runs.list.filters.allJobs")}</option>
          {jobs.data?.map((job) => (
            <option key={job.id} value={job.id}>
              {job.name}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="runs-filter-status">{t("runs.list.filters.status")}</Label>
        <Select
          id="runs-filter-status"
          value={status}
          onChange={(e) => update({ status: e.target.value })}
        >
          <option value="">{t("runs.list.filters.all")}</option>
          {RUN_STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(`runs.status.${s}`)}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="runs-filter-trigger">{t("runs.list.filters.trigger")}</Label>
        <Select
          id="runs-filter-trigger"
          value={client.trigger}
          onChange={(e) => update({ trigger: e.target.value })}
        >
          <option value="">{t("runs.list.filters.all")}</option>
          {RUN_TRIGGERS.map((tr) => (
            <option key={tr} value={tr}>
              {t(`runs.trigger.${tr}`)}
            </option>
          ))}
        </Select>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor="runs-filter-dry">{t("runs.list.filters.dryRun")}</Label>
        <Select
          id="runs-filter-dry"
          value={client.dryRun}
          onChange={(e) => update({ dry: e.target.value })}
        >
          <option value="">{t("runs.list.filters.all")}</option>
          <option value="yes">{t("runs.list.filters.dryRunYes")}</option>
          <option value="no">{t("runs.list.filters.dryRunNo")}</option>
        </Select>
      </div>
      {filtered && (
        <Button type="button" variant="ghost" onClick={() => setParams({}, { replace: true })}>
          {t("runs.list.filters.clear")}
        </Button>
      )}
    </form>
  );

  let body;
  if (runs.isPending) body = <Loading />;
  else if (runs.isError)
    body = <ErrorState error={runs.error} onRetry={() => void runs.refetch()} />;
  else if (visible.length === 0)
    body = <EmptyState message={t(filtered ? "runs.list.emptyFiltered" : "runs.list.empty")} />;
  else
    body = (
      <Table>
        <caption className="sr-only">{t("runs.list.caption")}</caption>
        <TableHeader>
          <TableRow>
            <TableHead>{t("runs.list.columns.id")}</TableHead>
            <TableHead>{t("runs.list.columns.job")}</TableHead>
            <TableHead>{t("runs.list.columns.trigger")}</TableHead>
            <TableHead>{t("runs.list.columns.status")}</TableHead>
            <TableHead>{t("runs.list.columns.started")}</TableHead>
            <TableHead>{t("runs.list.columns.finished")}</TableHead>
            <TableHead>{t("runs.list.columns.duration")}</TableHead>
            <TableHead>{t("runs.list.columns.counters")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {visible.map((run) => (
            <TableRow key={run.id}>
              <TableCell>
                <Link
                  to={`/runs/${run.id}`}
                  className="font-medium underline-offset-2 hover:underline"
                >
                  #{run.id}
                </Link>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-2">
                  <Link to={`/runs?job=${run.job_id}`} className="hover:underline">
                    {jobName(run)}
                  </Link>
                  {run.dry_run && <Badge variant="brand">{t("runs.dryRunBadge")}</Badge>}
                </div>
              </TableCell>
              <TableCell>
                {t(`runs.trigger.${run.trigger}`, { defaultValue: run.trigger })}
              </TableCell>
              <TableCell>
                <RunStatusBadge status={run.status} />
              </TableCell>
              <TableCell>{formatDateTime(run.started_at)}</TableCell>
              <TableCell>{run.finished_at ? formatDateTime(run.finished_at) : "—"}</TableCell>
              <TableCell>{formatDuration(runDurationSeconds(run, now))}</TableCell>
              <TableCell>
                <CounterSummary counters={run.counters} />
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

  return (
    <section className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold">{t("nav.runs")}</h1>
      {filters}
      {(client.trigger || client.dryRun) && (
        <p className="text-sm text-muted-foreground">{t("runs.list.clientFilterNote")}</p>
      )}
      {runs.data && (
        <p role="status" className={active > 0 ? "text-sm text-muted-foreground" : "sr-only"}>
          {active > 0
            ? `${t("runs.list.live", { count: active })}. ${t("runs.list.refreshing")}`
            : ""}
        </p>
      )}
      {body}
      {runs.data && (page > 1 || runs.data.hasNext) && (
        <Pagination
          page={page}
          hasNext={runs.data.hasNext}
          onPageChange={(next) => update({ page: next > 1 ? String(next) : null })}
        />
      )}
    </section>
  );
}
