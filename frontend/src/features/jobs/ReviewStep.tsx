import { useTranslation } from "react-i18next";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import type { Profile } from "@/features/connections/types";
import type { JobFormState } from "@/features/jobs/form";
import { toJobInput } from "@/features/jobs/form";
import { TriggerSummary } from "@/features/jobs/TriggerSummary";
import type { MappingRef } from "@/features/jobs/types";

function Entry({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5 sm:flex-row sm:gap-4">
      <dt className="text-sm text-muted-foreground sm:w-48 sm:shrink-0">{label}</dt>
      <dd className="min-w-0 break-words text-sm">{children}</dd>
    </div>
  );
}

/** Read-only summary of what will be saved, plus the "enabled" flag. */
export function ReviewStep({
  state,
  profiles,
  onEnabled,
}: {
  state: JobFormState;
  profiles: readonly Profile[];
  onEnabled: (enabled: boolean) => void;
}) {
  const { t } = useTranslation();
  const input = toJobInput(state);
  const profileName = (id: number) => profiles.find((p) => p.id === id)?.name ?? `#${id}`;
  const mapping = (ref: MappingRef) => (
    <>
      <code className="font-mono text-xs">{ref.name}</code>{" "}
      {ref.version === null ? t("jobs.wizard.review.latest") : `v${ref.version}`}
    </>
  );
  const filters = Object.entries(input.record_filter.equals);

  return (
    <div className="flex flex-col gap-6">
      <dl className="flex flex-col gap-3">
        <Entry label={t("jobs.wizard.review.name")}>{input.name}</Entry>
        <Entry label={t("jobs.wizard.review.direction")}>
          {t(`jobs.directions.${input.direction}`)}
        </Entry>
        <Entry label={t("jobs.wizard.review.source")}>
          {profileName(input.source.profile_id)} · {input.source.resource}
        </Entry>
        <Entry label={t("jobs.wizard.review.target")}>
          {profileName(input.target.profile_id)} · {input.target.resource}
        </Entry>
        <Entry label={t("jobs.wizard.review.mapping")}>{mapping(input.mapping)}</Entry>
        {input.reverse_mapping && (
          <Entry label={t("jobs.wizard.review.reverseMapping")}>
            {mapping(input.reverse_mapping)}
          </Entry>
        )}
        <Entry label={t("jobs.wizard.review.upsert")}>
          {input.upsert_key === "xref" ? (
            t("jobs.wizard.options.upsertXref")
          ) : (
            <code className="font-mono text-xs">{input.upsert_key.replace("field:", "")}</code>
          )}
        </Entry>
        <Entry label={t("jobs.wizard.review.filters")}>
          {filters.length === 0
            ? t("jobs.wizard.review.noFilters")
            : filters.map(([field, value]) => `${field} = ${JSON.stringify(value)}`).join(", ")}
        </Entry>
        <Entry label={t("jobs.wizard.review.batchSize")}>{input.batch_size}</Entry>
        {input.direction === "bidirectional" && (
          <Entry label={t("jobs.wizard.review.conflict")}>
            {t(`jobs.wizard.options.conflictRules.${input.conflict_rule}`)}
          </Entry>
        )}
        <Entry label={t("jobs.wizard.review.trigger")}>
          <TriggerSummary trigger={input.trigger} />
        </Entry>
      </dl>
      <div className="flex items-center gap-2">
        <Checkbox
          id="job-enabled"
          checked={state.enabled}
          onChange={(event) => onEnabled(event.target.checked)}
        />
        <Label htmlFor="job-enabled">{t("jobs.wizard.review.enabled")}</Label>
      </div>
      <p className="text-sm text-muted-foreground">{t("jobs.wizard.review.simulateHint")}</p>
    </div>
  );
}
