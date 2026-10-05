import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Loading } from "@/components/Loading";
import { useRun, useRunErrors } from "@/features/runs/hooks";
import { RunStatusBadge } from "@/features/runs/RunStatusBadge";
import { isActiveStatus } from "@/features/runs/summary";
import type { RunCounters } from "@/features/runs/types";

const COUNTERS: readonly (keyof RunCounters)[] = [
  "created",
  "updated",
  "skipped",
  "failed",
  "conflicts",
  "processed",
];
const MAX_TEXT = 300;
const clip = (text: string) => (text.length > MAX_TEXT ? `${text.slice(0, MAX_TEXT)}…` : text);

/**
 * Outcome of a dry run: status, counters and the first errors. The run is read until it
 * finishes; nothing here writes to the remote systems.
 */
export function SimulationResult({ runId }: { runId: number }) {
  const { t } = useTranslation();
  const run = useRun(runId);
  const finished = run.data !== undefined && !isActiveStatus(run.data.status);
  const errors = useRunErrors(runId, finished && (run.data?.error_count ?? 0) > 0);

  return (
    <section
      aria-label={t("jobs.wizard.sim.title")}
      className="flex flex-col gap-4 rounded-lg border p-4"
    >
      <h3 className="text-base font-semibold">{t("jobs.wizard.sim.title")}</h3>
      {run.isError && (
        <p role="alert" className="text-sm text-destructive">
          {t("common.unexpectedError")}
        </p>
      )}
      {!run.data && !run.isError && <Loading />}
      {run.data && !finished && (
        <p role="status" className="text-sm text-muted-foreground">
          {t("jobs.wizard.sim.running")}
        </p>
      )}
      {run.data && finished && (
        <>
          <div className="flex items-center gap-3">
            <RunStatusBadge status={run.data.status} />
            <Link
              to={`/runs/${run.data.id}`}
              className="text-sm font-medium underline underline-offset-2"
            >
              {t("jobs.run.view")}
            </Link>
          </div>
          {run.data.error && <p className="text-sm text-destructive">{clip(run.data.error)}</p>}
          <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
            {COUNTERS.map((counter) => (
              <div key={counter} className="flex flex-col rounded-md border p-2">
                <dt className="text-xs text-muted-foreground">
                  {t(`jobs.wizard.sim.counters.${counter}`)}
                </dt>
                <dd className="text-lg font-semibold">{run.data.counters[counter]}</dd>
              </div>
            ))}
          </dl>
          {errors.data && errors.data.items.length > 0 && (
            <div className="flex flex-col gap-2">
              <h4 className="text-sm font-medium">
                {t("jobs.wizard.sim.errorsTitle", {
                  shown: errors.data.items.length,
                  total: errors.data.total,
                })}
              </h4>
              <ul className="flex flex-col gap-1 text-sm">
                {errors.data.items.map((error) => (
                  <li key={error.id} className="break-words">
                    {error.record_ref && (
                      <code className="font-mono text-xs">{error.record_ref}</code>
                    )}{" "}
                    {clip(error.message)}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </section>
  );
}
