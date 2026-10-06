import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { ApiError } from "@/api/client";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { useJob } from "@/features/jobs/hooks";
import { formatDateTime } from "@/features/mappings/format";
import { describeCheckpoint } from "@/features/runs/checkpoint";
import { formatDuration, runDurationSeconds } from "@/features/runs/format";
import { useRun } from "@/features/runs/hooks";
import { isStale } from "@/features/runs/policy";
import { RunActions } from "@/features/runs/RunActions";
import { RunErrorsSection } from "@/features/runs/RunErrorsSection";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { type RunCounters, type RunDetail } from "@/features/runs/types";

const COUNTERS: readonly (keyof RunCounters)[] = [
  "processed",
  "created",
  "updated",
  "skipped",
  "failed",
  "conflicts",
];

function NotFound() {
  const { t } = useTranslation();
  return (
    <section className="flex flex-col items-start gap-3">
      <p role="alert">{t("runs.detail.notFound")}</p>
      <Link to="/runs" className="font-medium underline underline-offset-2">
        {t("runs.detail.back")}
      </Link>
    </section>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="text-sm">{children}</dd>
    </div>
  );
}

function RunBody({ run, now }: { run: RunDetail; now: number }) {
  const { t } = useTranslation();
  const job = useJob(run.job_id);
  const checkpoint = describeCheckpoint(run.checkpoint);
  const stale = isStale(run, now);
  const quietMinutes = Math.floor((now - Date.parse(run.heartbeat_at ?? run.started_at)) / 60_000);

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-2xl font-semibold">{t("runs.detail.title", { id: run.id })}</h1>
          <RunStatusBadge status={run.status} />
          {run.dry_run && <Badge variant="brand">{t("runs.dryRunBadge")}</Badge>}
        </div>
        {/* Screen readers hear status changes while the run is refreshed. */}
        <p role="status" className="sr-only">
          {t("runs.detail.live", { id: run.id, status: t(`runs.status.${run.status}`) })}
        </p>
        <RunActions run={run} now={now} />
        {run.cancel_requested && !run.finished_at && (
          <p className="text-sm text-muted-foreground">{t("runs.detail.cancelPending")}</p>
        )}
        {stale && (
          <p className="rounded-md border border-warning-soft-foreground/30 bg-warning-soft p-3 text-sm text-warning-soft-foreground">
            {t("runs.detail.stale", { minutes: quietMinutes })}
          </p>
        )}
        {run.error && (
          <div role="alert" className="rounded-md border border-destructive p-3 text-sm">
            <p className="font-medium text-destructive">{t("runs.detail.runError")}</p>
            <p className="whitespace-pre-wrap break-words">{run.error}</p>
          </div>
        )}
      </div>

      <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
        <Field label={t("runs.detail.job")}>
          <Link to={`/jobs/${run.job_id}/edit`} className="underline underline-offset-2">
            {job.data?.name ?? t("runs.unknownJob", { id: run.job_id })}
          </Link>
        </Field>
        <Field label={t("runs.detail.trigger")}>
          {t(`runs.trigger.${run.trigger}`, { defaultValue: run.trigger })}
        </Field>
        <Field label={t("runs.detail.started")}>{formatDateTime(run.started_at)}</Field>
        <Field label={t("runs.detail.finished")}>
          {run.finished_at ? formatDateTime(run.finished_at) : "—"}
        </Field>
        <Field label={t("runs.detail.duration")}>
          {formatDuration(runDurationSeconds(run, now))}
        </Field>
        <Field label={t("runs.detail.heartbeat")}>
          {run.heartbeat_at ? formatDateTime(run.heartbeat_at) : "—"}
        </Field>
        {run.parent_run_id !== null && (
          <Field label={t("runs.detail.parent")}>
            {t("runs.detail.parentText")}{" "}
            <Link
              to={`/runs/${run.parent_run_id}`}
              className="font-medium underline underline-offset-2"
            >
              #{run.parent_run_id}
            </Link>
          </Field>
        )}
      </dl>

      <section aria-labelledby="run-progress" className="flex flex-col gap-2">
        <h2 id="run-progress" className="text-lg font-semibold">
          {t("runs.detail.progress")}
        </h2>
        <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
          {COUNTERS.map((counter) => (
            <div key={counter} className="rounded-lg border p-3">
              <dt className="text-xs text-muted-foreground">
                {t(`runs.detail.counters.${counter}`)}
              </dt>
              <dd className="text-2xl font-semibold">{run.counters[counter]}</dd>
            </div>
          ))}
        </dl>
      </section>

      {checkpoint && (
        <section aria-labelledby="run-checkpoint" className="flex flex-col gap-2">
          <h2 id="run-checkpoint" className="text-lg font-semibold">
            {t("runs.detail.checkpoint")}
          </h2>
          <p className="text-sm text-muted-foreground">{t("runs.detail.checkpointHelp")}</p>
          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-4">
            <Field label={t("runs.detail.passLabel")}>
              {t(`runs.detail.pass.${checkpoint.pass}`, { defaultValue: checkpoint.pass })}
            </Field>
            {checkpoint.lastId !== null && (
              <Field label={t("runs.detail.lastId")}>
                <code className="font-mono text-xs">{checkpoint.lastId}</code>
              </Field>
            )}
            {checkpoint.done && <Field label={t("runs.detail.passDone")}>{t("common.yes")}</Field>}
            {checkpoint.maxUpdatedAt !== null && (
              <Field label={t("runs.detail.maxUpdatedAt")}>
                {formatDateTime(checkpoint.maxUpdatedAt)}
              </Field>
            )}
          </dl>
        </section>
      )}

      <RunErrorsSection run={run} />
    </section>
  );
}

export function RunDetailPage() {
  const params = useParams();
  const id = Number(params.id);
  const valid = Number.isInteger(id) && id > 0;
  const run = useRun(valid ? id : null);

  if (!valid) return <NotFound />;
  if (run.isPending) return <Loading />;
  if (run.isError) {
    if (run.error instanceof ApiError && run.error.status === 404) return <NotFound />;
    return <ErrorState error={run.error} onRetry={() => void run.refetch()} />;
  }
  return <RunBody run={run.data} now={run.dataUpdatedAt} />;
}
