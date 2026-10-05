import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { Button } from "@/components/ui/button";
import { Steps } from "@/components/ui/steps";
import { useToast } from "@/components/ui/toast";
import { useProfiles } from "@/features/connections/hooks";
import { describeJobError } from "@/features/jobs/errors";
import {
  checkMappings,
  emptyJobState,
  JOB_STEPS,
  stateFromJob,
  stepOfField,
  toJobInput,
  validateAll,
  validateStep,
  type JobFieldErrors,
  type JobFormState,
  type JobStep,
} from "@/features/jobs/form";
import { useSaveJob, useTriggerRun } from "@/features/jobs/hooks";
import { ReviewStep } from "@/features/jobs/ReviewStep";
import { SimulationResult } from "@/features/jobs/SimulationResult";
import { BasicsStep, EndpointsStep, OptionsStep, TriggerStep } from "@/features/jobs/steps";
import type { Job } from "@/features/jobs/types";
import { useMappings } from "@/features/mappings/hooks";
import { useSideSchema } from "@/features/mappings/SidePicker";

interface Failure {
  text: string;
  detail?: string;
}

/**
 * Five-step create/edit wizard. It validates each step before moving on, saves with POST or PUT
 * and can start a dry run right after saving (the API only simulates saved jobs).
 */
export function JobWizard({ job }: { job?: Job }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { toast } = useToast();
  const profiles = useProfiles();
  const mappings = useMappings();
  const save = useSaveJob();
  const simulate = useTriggerRun();

  const [state, setState] = useState<JobFormState>(() =>
    job ? stateFromJob(job) : emptyJobState(),
  );
  const [step, setStep] = useState(0);
  const [errors, setErrors] = useState<JobFieldErrors>({});
  const [failure, setFailure] = useState<Failure | null>(null);
  const [savedId, setSavedId] = useState<number | null>(null);
  const [runId, setRunId] = useState<number | null>(null);
  const [simulationFailed, setSimulationFailed] = useState(false);

  const sourceSchema = useSideSchema(state.sourceProfileId, state.sourceResource.trim());
  const targetSchema = useSideSchema(state.targetProfileId, state.targetResource.trim());

  const editing = job !== undefined;
  const stepId: JobStep = JOB_STEPS[step] ?? "basics";
  const patch = (changes: Partial<JobFormState>) => setState((prev) => ({ ...prev, ...changes }));
  const text = Object.fromEntries(
    Object.entries(errors).map(([field, key]) => [field, t(key)]),
  ) as Record<keyof JobFieldErrors, string | undefined>;

  const goTo = (index: number) => {
    setFailure(null);
    setStep(index);
  };

  function next() {
    let found = validateStep(stepId, state);
    if (stepId === "endpoints" && Object.keys(found).length === 0 && mappings.data) {
      found = checkMappings(state, mappings.data);
    }
    setErrors(found);
    if (Object.keys(found).length === 0) goTo(step + 1);
  }

  function fail(error: unknown, action: "save" | "dryRun") {
    const described = describeJobError(error, action);
    const message = t(described.messageKey, described.params);
    const pointed = Object.keys(described.fieldErrors) as (keyof JobFieldErrors)[];
    if (pointed.length > 0) {
      setErrors(described.fieldErrors);
      const earliest = Math.min(...pointed.map((field) => JOB_STEPS.indexOf(stepOfField(field))));
      setStep(earliest);
    }
    // A message that only repeats the field error would show the same sentence twice.
    setFailure(
      pointed.length > 0 && !described.detail ? null : { text: message, detail: described.detail },
    );
  }

  function persist(then: (saved: Job) => void) {
    const complete = validateAll(state);
    if (Object.keys(complete).length > 0) {
      setErrors(complete);
      setStep(
        Math.min(
          ...(Object.keys(complete) as (keyof JobFieldErrors)[]).map((f) =>
            JOB_STEPS.indexOf(stepOfField(f)),
          ),
        ),
      );
      return;
    }
    setFailure(null);
    save.mutate(
      { id: job?.id ?? savedId ?? undefined, input: toJobInput(state) },
      { onSuccess: then, onError: (error) => fail(error, "save") },
    );
  }

  const saveAndLeave = () =>
    persist((saved) => {
      toast({ tone: "success", message: t("jobs.wizard.saved", { name: saved.name }) });
      void navigate("/jobs");
    });

  const saveAndSimulate = () =>
    persist((saved) => {
      setSavedId(saved.id);
      simulate.mutate(
        { jobId: saved.id, dryRun: true },
        {
          onSuccess: (run) => setRunId(run.id),
          onError: (error) => {
            const described = describeJobError(error, "dryRun");
            setSimulationFailed(true);
            setFailure({
              text: `${t("jobs.wizard.sim.notStarted")} ${t(described.messageKey, described.params)}`,
              detail: described.detail,
            });
          },
        },
      );
    });

  const busy = save.isPending || simulate.isPending;
  const finished = savedId !== null && (runId !== null || simulationFailed);

  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">
        {t(editing ? "jobs.wizard.titleEdit" : "jobs.wizard.titleCreate")}
      </h1>
      <Steps
        label={t("jobs.wizard.stepsLabel")}
        current={step}
        items={JOB_STEPS.map((id) => ({ id, label: t(`jobs.wizard.steps.${id}`) }))}
      />
      <h2 className="text-lg font-semibold">{t(`jobs.wizard.steps.${stepId}`)}</h2>

      {failure && (
        <div role="alert" className="flex flex-col gap-1 text-sm text-destructive">
          <p>{failure.text}</p>
          {failure.detail && <p className="break-words text-muted-foreground">{failure.detail}</p>}
        </div>
      )}

      {stepId === "basics" && <BasicsStep state={state} errors={text} patch={patch} />}
      {stepId === "endpoints" && (
        <EndpointsStep
          state={state}
          errors={text}
          patch={patch}
          profiles={profiles.data ?? []}
          mappings={mappings.data ?? []}
          sourceSchema={sourceSchema}
          targetSchema={targetSchema}
        />
      )}
      {stepId === "options" && (
        <OptionsStep
          state={state}
          errors={text}
          patch={patch}
          sourceFields={(sourceSchema.fields ?? []).map((f) => f.name)}
          targetFields={(targetSchema.fields ?? []).map((f) => f.name)}
        />
      )}
      {stepId === "trigger" && <TriggerStep state={state} errors={text} patch={patch} />}
      {stepId === "review" && (
        <ReviewStep
          state={state}
          profiles={profiles.data ?? []}
          onEnabled={(enabled) => patch({ enabled })}
        />
      )}

      {runId !== null && <SimulationResult runId={runId} />}

      <div className="flex flex-wrap justify-between gap-2">
        {finished ? (
          <Button type="button" onClick={() => void navigate("/jobs")}>
            {t("jobs.wizard.backToList")}
          </Button>
        ) : (
          <>
            <Button
              type="button"
              variant="outline"
              disabled={step === 0 || busy}
              onClick={() => goTo(step - 1)}
            >
              {t("jobs.wizard.previous")}
            </Button>
            {stepId === "review" ? (
              <div className="flex gap-2">
                <Button type="button" variant="outline" disabled={busy} onClick={saveAndSimulate}>
                  {t("jobs.wizard.saveAndSimulate")}
                </Button>
                <Button type="button" disabled={busy} onClick={saveAndLeave}>
                  {t("jobs.wizard.save")}
                </Button>
              </div>
            ) : (
              <Button type="button" onClick={next}>
                {t("jobs.wizard.next")}
              </Button>
            )}
          </>
        )}
      </div>
    </section>
  );
}
