import { useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Play, RefreshCw } from "lucide-react";
import { useState, type ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useActiveOdoo } from "@/features/connections/hooks";
import { LastConnected } from "@/features/connections/LastConnected";
import { DASHBOARD_KEY } from "@/features/dashboard/api";
import {
  attentionItems,
  dashboardRefetchInterval,
  nextFireOf,
  odooAttention,
  runsByDay,
  type AttentionItem,
} from "@/features/dashboard/derive";
import { useDashboard, useRecentRuns } from "@/features/dashboard/hooks";
import { OutcomeChart } from "@/features/dashboard/OutcomeChart";
import type { Dashboard } from "@/features/dashboard/types";
import { useJobs } from "@/features/jobs/hooks";
import { RunNowDialog } from "@/features/jobs/RunNowDialog";
import { TriggerSummary } from "@/features/jobs/TriggerSummary";
import type { Job } from "@/features/jobs/types";
import { cn } from "@/lib/utils";
import { formatDateTime } from "@/features/mappings/format";
import { formatDuration, runDurationSeconds } from "@/features/runs/format";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { CounterSummary } from "@/features/runs/RunsPage";
import { latestRunByJob } from "@/features/runs/summary";
import { RUN_STATUSES } from "@/features/runs/types";

const CHART_DAYS = 7;
const RECENT_LIMIT = 200;

function Section({
  id,
  title,
  actions,
  children,
}: {
  id: string;
  title: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 id={id} className="text-lg font-semibold">
          {title}
        </h2>
        {actions}
      </div>
      {children}
    </section>
  );
}

function StatCard({
  to,
  label,
  value,
  children,
}: {
  to: string;
  label: string;
  value: number;
  children?: ReactNode;
}) {
  return (
    <Card className="transition-all hover:-translate-y-0.5 hover:shadow-lift">
      <Link to={to} className="flex h-full flex-col gap-1 p-4">
        <span className="text-sm text-muted-foreground">{label}</span>
        <span className="text-3xl font-semibold tabular-nums">{value}</span>
        {children}
      </Link>
    </Card>
  );
}

function Summary({ query }: { query: ReturnType<typeof useDashboard> }) {
  const { t } = useTranslation();
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const data: Dashboard = query.data;
  const counts = data.runs_last_24h;
  const total24h = RUN_STATUSES.reduce((sum, status) => sum + (counts[status] ?? 0), 0);
  const failures = (counts.failed ?? 0) + (counts.partial ?? 0);
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
      <StatCard
        to="/connections"
        label={t("dashboard.summary.connections")}
        value={data.profiles}
      />
      <StatCard to="/mappings" label={t("dashboard.summary.mappings")} value={data.mappings} />
      <StatCard to="/jobs" label={t("dashboard.summary.jobs")} value={data.jobs_total}>
        <span className="text-xs text-muted-foreground">
          {t("dashboard.summary.jobsEnabled", { count: data.jobs_enabled })}
        </span>
      </StatCard>
      <StatCard to="/runs" label={t("dashboard.summary.active")} value={data.active_runs.length} />
      <StatCard to="/runs" label={t("dashboard.summary.last24h")} value={total24h}>
        {total24h === 0 ? (
          <span className="text-xs text-muted-foreground">
            {t("dashboard.summary.last24hNone")}
          </span>
        ) : (
          <ul className="flex flex-wrap gap-x-3 text-xs text-muted-foreground">
            {RUN_STATUSES.filter((status) => (counts[status] ?? 0) > 0).map((status) => (
              <li key={status}>
                {t(`runs.status.${status}`)} {counts[status]}
              </li>
            ))}
          </ul>
        )}
      </StatCard>
      <StatCard to="/runs?status=failed" label={t("dashboard.summary.failures")} value={failures}>
        <span className="text-xs text-muted-foreground">{t("dashboard.summary.failuresHint")}</span>
      </StatCard>
    </div>
  );
}

function ActiveOdooCard() {
  const { t } = useTranslation();
  const query = useActiveOdoo();
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const active = query.data;
  const none = active.source === "none";
  return (
    <Card className="flex flex-col gap-2 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {none ? (
          <span className="font-medium text-destructive">{t("dashboard.odoo.none")}</span>
        ) : (
          <span className="font-medium">{active.profile_name ?? t("connections.kinds.odoo")}</span>
        )}
        <Badge variant={active.status === "active" ? "success" : "outline"}>
          {t(`connections.active.status.${active.status}`)}
        </Badge>
      </div>
      {!none && (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm">
          <dt className="text-muted-foreground">{t("connections.active.fields.source")}</dt>
          <dd>{t(`connections.active.source.${active.source}`)}</dd>
          <dt className="text-muted-foreground">{t("connections.active.fields.lastConnected")}</dt>
          <dd>
            <LastConnected iso={active.last_connected_at} now={query.dataUpdatedAt} />
          </dd>
        </dl>
      )}
      <Link
        to="/connections"
        className="inline-flex w-fit items-center gap-1 rounded-sm text-sm font-medium text-primary underline-offset-4 hover:underline focus-visible:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring"
      >
        {t("dashboard.odoo.view")}
        <ArrowRight aria-hidden className="size-4" />
      </Link>
    </Card>
  );
}

function AttentionPanel({
  dashboard,
  recent,
  jobs,
  jobName,
}: {
  dashboard: ReturnType<typeof useDashboard>;
  recent: ReturnType<typeof useRecentRuns>;
  jobs: ReturnType<typeof useJobs>;
  jobName: (id: number) => string;
}) {
  const { t } = useTranslation();
  const activeOdoo = useActiveOdoo();
  if (dashboard.isPending) return <Loading />;
  if (dashboard.isError)
    return <ErrorState error={dashboard.error} onRetry={() => void dashboard.refetch()} />;
  const items = attentionItems({
    failures: dashboard.data.recent_failures,
    active: dashboard.data.active_runs,
    recent: recent.data ?? [],
    jobs: jobs.data ?? [],
    now: dashboard.dataUpdatedAt,
  });
  const incomplete = recent.isError || jobs.isError;
  const odoo = odooAttention(activeOdoo.data);
  if (items.length === 0 && odoo === null) {
    if (recent.isPending || jobs.isPending) return <Loading />;
    return incomplete ? (
      <p role="status" className="text-sm text-muted-foreground">
        {t("dashboard.attention.incomplete")}
      </p>
    ) : (
      <p className="rounded-lg border p-4 text-sm text-muted-foreground">
        {t("dashboard.attention.allGood")}
      </p>
    );
  }
  const describe = (item: AttentionItem): { to: string; text: string } => {
    if (item.kind === "failedRun")
      return {
        to: `/runs/${item.run.id}`,
        text: t("dashboard.attention.failedRun", {
          id: item.run.id,
          job: jobName(item.run.job_id),
          status: t(`runs.status.${item.run.status}`),
        }),
      };
    if (item.kind === "staleRun")
      return {
        to: `/runs/${item.run.id}`,
        text: t("dashboard.attention.staleRun", {
          id: item.run.id,
          job: jobName(item.run.job_id),
        }),
      };
    return {
      to: `/runs?job=${item.jobId}`,
      text: t("dashboard.attention.repeated", { job: item.name, count: item.count }),
    };
  };
  return (
    <>
      <ul className="flex flex-col gap-2">
        {odoo !== null && (
          <li className="rounded-lg border border-destructive/40">
            <Link to="/connections" className="block p-3 text-sm hover:underline">
              {t(
                odoo === "none"
                  ? "dashboard.attention.odooNone"
                  : "dashboard.attention.odooFallback",
              )}
            </Link>
          </li>
        )}
        {items.map((item) => {
          const { to, text } = describe(item);
          const key =
            item.kind === "repeatedFailures" ? `job-${item.jobId}` : `${item.kind}-${item.run.id}`;
          return (
            <li key={key} className="rounded-lg border border-destructive/40">
              <Link to={to} className="block p-3 text-sm hover:underline">
                {text}
              </Link>
            </li>
          );
        })}
      </ul>
      {incomplete && (
        <p role="status" className="text-xs text-muted-foreground">
          {t("dashboard.attention.incomplete")}
        </p>
      )}
    </>
  );
}

function RecentRuns({
  query,
  jobName,
}: {
  query: ReturnType<typeof useDashboard>;
  jobName: (id: number) => string;
}) {
  const { t } = useTranslation();
  if (query.isPending) return <Loading />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  if (query.data.recent_runs.length === 0)
    return <EmptyState message={t("dashboard.recent.empty")} />;
  const now = query.dataUpdatedAt;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("runs.list.columns.id")}</TableHead>
          <TableHead>{t("runs.list.columns.job")}</TableHead>
          <TableHead>{t("runs.list.columns.status")}</TableHead>
          <TableHead>{t("runs.list.columns.started")}</TableHead>
          <TableHead>{t("runs.list.columns.duration")}</TableHead>
          <TableHead>{t("runs.list.columns.counters")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {query.data.recent_runs.map((run) => (
          <TableRow key={run.id}>
            <TableCell>
              <Link to={`/runs/${run.id}`} className="font-medium hover:underline">
                #{run.id}
              </Link>
              {run.dry_run && (
                <Badge variant="outline" className="ml-2">
                  {t("runs.dryRunBadge")}
                </Badge>
              )}
            </TableCell>
            <TableCell>{jobName(run.job_id)}</TableCell>
            <TableCell>
              <RunStatusBadge status={run.status} />
            </TableCell>
            <TableCell>{formatDateTime(run.started_at)}</TableCell>
            <TableCell>{formatDuration(runDurationSeconds(run, now))}</TableCell>
            <TableCell>
              <CounterSummary counters={run.counters} />
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function JobsSection({
  jobs,
  dashboard,
  recent,
  onRun,
}: {
  jobs: ReturnType<typeof useJobs>;
  dashboard: ReturnType<typeof useDashboard>;
  recent: ReturnType<typeof useRecentRuns>;
  onRun: (job: Job) => void;
}) {
  const { t } = useTranslation();
  if (jobs.isPending) return <Loading />;
  if (jobs.isError) return <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />;
  if (jobs.data.length === 0) return <EmptyState message={t("dashboard.jobs.empty")} />;
  const lastRuns = recent.data ? latestRunByJob(recent.data) : null;
  const now = new Date(dashboard.dataUpdatedAt);

  const lastRun = (job: Job) => {
    if (recent.isPending) return <span className="text-muted-foreground">…</span>;
    const run = lastRuns?.get(job.id);
    if (!lastRuns) return t("jobs.lastRun.unavailable");
    if (!run) return t("jobs.lastRun.none");
    return (
      <Link to={`/runs/${run.id}`} className="inline-flex flex-col gap-1 hover:underline">
        <RunStatusBadge status={run.status} />
        <span className="text-xs text-muted-foreground">{formatDateTime(run.started_at)}</span>
      </Link>
    );
  };

  const nextFire = (job: Job) => {
    if (dashboard.isPending) return <span className="text-muted-foreground">…</span>;
    if (dashboard.isError) return t("jobs.lastRun.unavailable");
    const scheduled = dashboard.data.scheduled.find((s) => s.job_id === job.id);
    const next = scheduled ? nextFireOf(scheduled, now) : null;
    if (!next) return "—";
    return (
      <>
        {formatDateTime(next.at)}
        {next.estimated && (
          <span className="ml-1 text-xs text-muted-foreground">
            {t("dashboard.jobs.estimated")}
          </span>
        )}
      </>
    );
  };

  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t("dashboard.jobs.columns.name")}</TableHead>
          <TableHead>{t("dashboard.jobs.columns.state")}</TableHead>
          <TableHead>{t("dashboard.jobs.columns.trigger")}</TableHead>
          <TableHead>{t("dashboard.jobs.columns.lastRun")}</TableHead>
          <TableHead>{t("dashboard.jobs.columns.nextFire")}</TableHead>
          <AdminOnly>
            <TableHead>
              <span className="sr-only">{t("dashboard.jobs.columns.actions")}</span>
            </TableHead>
          </AdminOnly>
        </TableRow>
      </TableHeader>
      <TableBody>
        {jobs.data.map((job) => (
          <TableRow key={job.id}>
            <TableCell className="font-medium">{job.name}</TableCell>
            <TableCell>
              <Badge variant={job.enabled ? "success" : "outline"}>
                {t(job.enabled ? "dashboard.jobs.enabled" : "dashboard.jobs.paused")}
              </Badge>
            </TableCell>
            <TableCell>
              <TriggerSummary trigger={job.trigger} />
            </TableCell>
            <TableCell>{lastRun(job)}</TableCell>
            <TableCell>{nextFire(job)}</TableCell>
            <AdminOnly>
              <TableCell>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t("jobs.actions.runNow", { name: job.name })}
                  onClick={() => onRun(job)}
                >
                  <Play aria-hidden className="size-4" />
                </Button>
              </TableCell>
            </AdminOnly>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

function OutcomeSection({ recent }: { recent: ReturnType<typeof useRecentRuns> }) {
  const { t } = useTranslation();
  if (recent.isPending) return <Loading />;
  if (recent.isError)
    return <ErrorState error={recent.error} onRetry={() => void recent.refetch()} />;
  const buckets = runsByDay(recent.data, new Date(recent.dataUpdatedAt), CHART_DAYS);
  if (buckets.every((bucket) => bucket.total === 0))
    return <EmptyState message={t("dashboard.chart.empty")} />;
  return (
    <>
      <OutcomeChart buckets={buckets} />
      {recent.data.length >= RECENT_LIMIT && (
        <p className="text-xs text-muted-foreground">{t("dashboard.chart.truncated")}</p>
      )}
    </>
  );
}

export function DashboardPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const dashboard = useDashboard();
  const interval = dashboardRefetchInterval(dashboard.data, document.hidden);
  const recent = useRecentRuns(interval);
  const jobs = useJobs();
  const [toRun, setToRun] = useState<Job | null>(null);

  const jobName = (id: number) =>
    jobs.data?.find((job) => job.id === id)?.name ?? t("runs.unknownJob", { id });
  const refreshing = dashboard.isFetching || recent.isFetching || jobs.isFetching;
  const refresh = () => Promise.all([dashboard.refetch(), recent.refetch(), jobs.refetch()]);

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("nav.dashboard")}</h1>
        <div className="flex items-center gap-3">
          <span role="status" className="text-xs text-muted-foreground">
            {refreshing ? t("dashboard.refreshing") : null}
          </span>
          <Button
            variant="outline"
            onClick={() => void refresh()}
            disabled={refreshing}
            aria-busy={refreshing}
          >
            <RefreshCw aria-hidden className={cn("size-4", refreshing && "animate-spin")} />
            {t("dashboard.refresh")}
          </Button>
        </div>
      </div>
      <Section id="dash-summary" title={t("dashboard.summary.title")}>
        <Summary query={dashboard} />
      </Section>
      <Section id="dash-odoo" title={t("dashboard.odoo.title")}>
        <ActiveOdooCard />
      </Section>
      <Section id="dash-attention" title={t("dashboard.attention.title")}>
        <AttentionPanel dashboard={dashboard} recent={recent} jobs={jobs} jobName={jobName} />
      </Section>
      <Section
        id="dash-recent"
        title={t("dashboard.recent.title")}
        actions={
          <Button variant="ghost" size="sm" asChild>
            <Link to="/runs">{t("dashboard.recent.viewAll")}</Link>
          </Button>
        }
      >
        <RecentRuns query={dashboard} jobName={jobName} />
      </Section>
      <Section id="dash-jobs" title={t("dashboard.jobs.title")}>
        <JobsSection jobs={jobs} dashboard={dashboard} recent={recent} onRun={setToRun} />
      </Section>
      <Section id="dash-chart" title={t("dashboard.chart.title")}>
        <OutcomeSection recent={recent} />
      </Section>
      <RunNowDialog
        job={toRun}
        onClose={() => {
          setToRun(null);
          void queryClient.invalidateQueries({ queryKey: DASHBOARD_KEY });
        }}
      />
    </div>
  );
}
