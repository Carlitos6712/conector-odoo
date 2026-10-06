import { FlaskConical, Pencil, Play, Plus, Trash2 } from "lucide-react";
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
import { Switch } from "@/components/ui/switch";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useToast } from "@/components/ui/toast";
import { useProfiles } from "@/features/connections/hooks";
import type { Profile } from "@/features/connections/types";
import { DeleteJobDialog } from "@/features/jobs/DeleteJobDialog";
import { describeJobError } from "@/features/jobs/errors";
import { useJobs, useSetJobEnabled, useTriggerRun } from "@/features/jobs/hooks";
import { RunNowDialog } from "@/features/jobs/RunNowDialog";
import { TriggerSummary } from "@/features/jobs/TriggerSummary";
import type { EndpointRef, Job } from "@/features/jobs/types";
import { formatDateTime } from "@/features/mappings/format";
import { useLastRuns } from "@/features/runs/hooks";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";

const endpointLabel = (ref: EndpointRef, profiles: readonly Profile[] | undefined): string => {
  const profile = profiles?.find((p) => p.id === ref.profile_id);
  return `${profile?.name ?? `#${ref.profile_id}`} · ${ref.resource}`;
};

function LastRun({ job }: { job: Job }) {
  const { t } = useTranslation();
  const runs = useLastRuns();
  if (runs.isPending) return <span className="text-muted-foreground">…</span>;
  if (runs.isError) return <span>{t("jobs.lastRun.unavailable")}</span>;
  const run = runs.data.get(job.id);
  if (!run) return <span>{t("jobs.lastRun.none")}</span>;
  return (
    <Link to={`/runs/${run.id}`} className="inline-flex flex-col gap-1 hover:underline">
      <RunStatusBadge status={run.status} />
      <span className="text-xs text-muted-foreground">{formatDateTime(run.started_at)}</span>
    </Link>
  );
}

export function JobsPage() {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const { toast } = useToast();
  const jobs = useJobs();
  const profiles = useProfiles();
  const setEnabled = useSetJobEnabled();
  const dryRun = useTriggerRun();
  const [toRun, setToRun] = useState<Job | null>(null);
  const [toDelete, setToDelete] = useState<Job | null>(null);

  const fail = (error: unknown, action: "toggle" | "dryRun") => {
    const described = describeJobError(error, action);
    toast({ tone: "error", message: t(described.messageKey, described.params) });
  };
  const toggle = (job: Job, enabled: boolean) =>
    setEnabled.mutate({ job, enabled }, { onError: (error) => fail(error, "toggle") });
  const simulate = (job: Job) =>
    dryRun.mutate(
      { jobId: job.id, dryRun: true },
      {
        onSuccess: (run) =>
          toast({
            tone: "success",
            message: t("jobs.run.dryStarted", { id: run.id }),
            action: { label: t("jobs.run.view"), to: `/runs/${run.id}` },
          }),
        onError: (error) => fail(error, "dryRun"),
      },
    );

  const create = (
    <AdminOnly>
      <Button asChild>
        <Link to="/jobs/new">
          <Plus aria-hidden className="size-4" />
          {t("jobs.new")}
        </Link>
      </Button>
    </AdminOnly>
  );

  let body;
  if (jobs.isPending) body = <Loading />;
  else if (jobs.isError)
    body = <ErrorState error={jobs.error} onRetry={() => void jobs.refetch()} />;
  else if (jobs.data.length === 0)
    body = (
      <EmptyState message={t(canMutate ? "jobs.empty" : "jobs.emptyReadOnly")} action={create} />
    );
  else
    body = (
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t("jobs.columns.name")}</TableHead>
            <TableHead>{t("jobs.columns.source")}</TableHead>
            <TableHead>{t("jobs.columns.target")}</TableHead>
            <TableHead>{t("jobs.columns.direction")}</TableHead>
            <TableHead>{t("jobs.columns.trigger")}</TableHead>
            <TableHead>{t("jobs.columns.nextFire")}</TableHead>
            <TableHead>{t("jobs.columns.enabled")}</TableHead>
            <TableHead>{t("jobs.columns.lastRun")}</TableHead>
            <TableHead>
              <span className="sr-only">{t("jobs.columns.actions")}</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {jobs.data.map((job) => (
            <TableRow key={job.id}>
              <TableCell className="font-medium">{job.name}</TableCell>
              <TableCell className="text-xs">{endpointLabel(job.source, profiles.data)}</TableCell>
              <TableCell className="text-xs">{endpointLabel(job.target, profiles.data)}</TableCell>
              <TableCell>
                <Badge variant="outline">{t(`jobs.directions.${job.direction}`)}</Badge>
              </TableCell>
              <TableCell>
                <TriggerSummary trigger={job.trigger} />
              </TableCell>
              <TableCell>{job.next_fire ? formatDateTime(job.next_fire) : "—"}</TableCell>
              <TableCell>
                <Switch
                  checked={job.enabled}
                  disabled={
                    !canMutate || (setEnabled.isPending && setEnabled.variables?.job.id === job.id)
                  }
                  aria-label={t("jobs.enabledLabel", { name: job.name })}
                  onCheckedChange={(enabled) => toggle(job, enabled)}
                />
              </TableCell>
              <TableCell>
                <LastRun job={job} />
              </TableCell>
              <TableCell>
                <AdminOnly>
                  <div className="flex justify-end gap-1">
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("jobs.actions.runNow", { name: job.name })}
                      onClick={() => setToRun(job)}
                    >
                      <Play aria-hidden className="size-4" />
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("jobs.actions.dryRun", { name: job.name })}
                      disabled={dryRun.isPending}
                      onClick={() => simulate(job)}
                    >
                      <FlaskConical aria-hidden className="size-4" />
                    </Button>
                    <Button variant="ghost" size="icon" asChild>
                      <Link
                        to={`/jobs/${job.id}/edit`}
                        aria-label={t("jobs.actions.edit", { name: job.name })}
                      >
                        <Pencil aria-hidden className="size-4" />
                      </Link>
                    </Button>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={t("jobs.actions.delete", { name: job.name })}
                      onClick={() => setToDelete(job)}
                    >
                      <Trash2 aria-hidden className="size-4" />
                    </Button>
                  </div>
                </AdminOnly>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    );

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("nav.jobs")}</h1>
        {jobs.data && jobs.data.length > 0 && create}
      </div>
      {body}
      <RunNowDialog job={toRun} onClose={() => setToRun(null)} />
      <DeleteJobDialog job={toDelete} onClose={() => setToDelete(null)} />
    </section>
  );
}
