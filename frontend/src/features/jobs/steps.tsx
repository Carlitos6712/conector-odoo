import { Plus, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { CheckboxGroup } from "@/components/ui/checkbox-group";
import { Input } from "@/components/ui/input";
import { RadioGroup } from "@/components/ui/radio-group";
import { Select } from "@/components/ui/select";
import type { Profile } from "@/features/connections/types";
import { FormField } from "@/features/connections/FormField";
import { CronEditor } from "@/features/jobs/CronEditor";
import { compatibleMappings, type JobFieldErrors, type JobFormState } from "@/features/jobs/form";
import { MappingPicker } from "@/features/jobs/MappingPicker";
import {
  CONFLICT_RULES,
  DIRECTIONS,
  KNOWN_EVENT_TYPES,
  type ConflictRule,
  type Direction,
} from "@/features/jobs/types";
import { SidePicker, type SchemaState } from "@/features/mappings/SidePicker";
import type { StoredMapping } from "@/features/mappings/types";

export interface StepProps {
  state: JobFormState;
  /** Translated field errors, ready to show. */
  errors: Partial<Record<keyof JobFieldErrors, string>>;
  patch: (changes: Partial<JobFormState>) => void;
}

// -- step 1 ------------------------------------------------------------------------------------

export function BasicsStep({ state, errors, patch }: StepProps) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-4">
      <FormField name="name" label={t("jobs.wizard.basics.name")} error={errors.name}>
        {(props) => (
          <Input {...props} value={state.name} onChange={(e) => patch({ name: e.target.value })} />
        )}
      </FormField>
      <RadioGroup
        legend={t("jobs.wizard.basics.direction")}
        name="direction"
        value={state.direction}
        options={DIRECTIONS.map((direction) => ({
          value: direction,
          label: t(`jobs.directions.${direction}`),
          description: t(`jobs.wizard.basics.hints.${direction}`),
        }))}
        onChange={(direction) => patch({ direction: direction as Direction })}
      />
    </div>
  );
}

// -- step 2 ------------------------------------------------------------------------------------

export function EndpointsStep({
  state,
  errors,
  patch,
  profiles,
  mappings,
  sourceSchema,
  targetSchema,
}: StepProps & {
  profiles: readonly Profile[];
  mappings: readonly StoredMapping[];
  sourceSchema: SchemaState;
  targetSchema: SchemaState;
}) {
  const { t } = useTranslation();
  const source = state.sourceResource.trim();
  const target = state.targetResource.trim();
  const forward = compatibleMappings(mappings, source, target);
  const backward = compatibleMappings(mappings, target, source);
  const bothChosen = source !== "" && target !== "";
  const twoWay = state.direction !== "a_to_b";

  return (
    <div className="flex flex-col gap-6">
      <div className="grid gap-6 md:grid-cols-2">
        <div className="flex flex-col gap-2">
          <SidePicker
            side="source"
            profiles={profiles}
            profileId={state.sourceProfileId}
            resource={state.sourceResource}
            schema={sourceSchema}
            fieldsListId="job-source-fields-picker"
            onProfile={(sourceProfileId) => patch({ sourceProfileId, sourceResource: "" })}
            onResource={(sourceResource) => patch({ sourceResource })}
          />
          {(errors.sourceProfile ?? errors.sourceResource) && (
            <p className="text-sm text-destructive">
              {errors.sourceProfile ?? errors.sourceResource}
            </p>
          )}
        </div>
        <div className="flex flex-col gap-2">
          <SidePicker
            side="target"
            profiles={profiles}
            profileId={state.targetProfileId}
            resource={state.targetResource}
            schema={targetSchema}
            fieldsListId="job-target-fields-picker"
            onProfile={(targetProfileId) => patch({ targetProfileId, targetResource: "" })}
            onResource={(targetResource) => patch({ targetResource })}
          />
          {(errors.targetProfile ?? errors.targetResource) && (
            <p className="text-sm text-destructive">
              {errors.targetProfile ?? errors.targetResource}
            </p>
          )}
        </div>
      </div>

      <MappingPicker
        id="mapping"
        label={t("jobs.wizard.endpoints.mapping")}
        versionLabel={t("jobs.wizard.endpoints.mappingVersion")}
        hint={t(bothChosen ? "jobs.wizard.endpoints.hint" : "jobs.wizard.endpoints.pickSidesFirst")}
        compatible={forward}
        name={state.mappingName}
        version={state.mappingVersion}
        error={errors.mapping}
        noneFits={bothChosen ? { source, target } : undefined}
        onName={(mappingName) => patch({ mappingName, mappingVersion: "" })}
        onVersion={(mappingVersion) => patch({ mappingVersion })}
      />
      {twoWay && (
        <MappingPicker
          id="reverseMapping"
          label={t("jobs.wizard.endpoints.reverseMapping")}
          versionLabel={t("jobs.wizard.endpoints.reverseVersion")}
          hint={t("jobs.wizard.endpoints.reverseHint")}
          compatible={backward}
          name={state.reverseName}
          version={state.reverseVersion}
          error={errors.reverseMapping}
          noneFits={bothChosen ? { source: target, target: source } : undefined}
          onName={(reverseName) => patch({ reverseName, reverseVersion: "" })}
          onVersion={(reverseVersion) => patch({ reverseVersion })}
        />
      )}
    </div>
  );
}

// -- step 3 ------------------------------------------------------------------------------------

export const SOURCE_FIELDS_ID = "job-source-fields";
export const TARGET_FIELDS_ID = "job-target-fields";

export function OptionsStep({
  state,
  errors,
  patch,
  sourceFields,
  targetFields,
}: StepProps & { sourceFields: readonly string[]; targetFields: readonly string[] }) {
  const { t } = useTranslation();
  const setRow = (index: number, change: Partial<JobFormState["filters"][number]>) =>
    patch({
      filters: state.filters.map((row, i) => (i === index ? { ...row, ...change } : row)),
    });

  return (
    <div className="flex flex-col gap-6">
      <datalist id={SOURCE_FIELDS_ID}>
        {sourceFields.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>
      <datalist id={TARGET_FIELDS_ID}>
        {targetFields.map((name) => (
          <option key={name} value={name} />
        ))}
      </datalist>

      <div className="flex flex-col gap-3">
        <RadioGroup
          legend={t("jobs.wizard.options.upsert")}
          name="upsert"
          value={state.upsertKind}
          options={[
            {
              value: "xref",
              label: t("jobs.wizard.options.upsertXref"),
              description: t("jobs.wizard.options.upsertXrefHint"),
            },
            {
              value: "field",
              label: t("jobs.wizard.options.upsertField"),
              description: t("jobs.wizard.options.upsertFieldHint"),
            },
          ]}
          onChange={(kind) => patch({ upsertKind: kind === "field" ? "field" : "xref" })}
        />
        {state.upsertKind === "field" && (
          <FormField
            name="upsertField"
            label={t("jobs.wizard.options.upsertFieldName")}
            error={errors.upsertField}
          >
            {(props) => (
              <Input
                {...props}
                list={TARGET_FIELDS_ID}
                className="font-mono text-xs"
                value={state.upsertField}
                onChange={(e) => patch({ upsertField: e.target.value })}
              />
            )}
          </FormField>
        )}
      </div>

      <fieldset
        className="flex flex-col gap-3"
        aria-describedby={errors.filters ? "job-filters-error" : "job-filters-hint"}
      >
        <legend className="mb-1 text-sm font-medium">{t("jobs.wizard.options.filter")}</legend>
        <p id="job-filters-hint" className="text-sm text-muted-foreground">
          {t("jobs.wizard.options.filterHint")}
        </p>
        {state.filters.map((row, index) => (
          <div key={index} className="flex flex-wrap items-center gap-2">
            <Input
              aria-label={t("jobs.wizard.options.filterField", { n: index + 1 })}
              list={SOURCE_FIELDS_ID}
              className="w-48 font-mono text-xs"
              value={row.field}
              onChange={(e) => setRow(index, { field: e.target.value })}
            />
            <span aria-hidden className="text-sm text-muted-foreground">
              =
            </span>
            <Input
              aria-label={t("jobs.wizard.options.filterValue", { n: index + 1 })}
              className="w-48 font-mono text-xs"
              value={row.value}
              onChange={(e) => setRow(index, { value: e.target.value })}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              aria-label={t("jobs.wizard.options.filterRemove", { n: index + 1 })}
              onClick={() => patch({ filters: state.filters.filter((_, i) => i !== index) })}
            >
              <Trash2 aria-hidden className="size-4" />
            </Button>
          </div>
        ))}
        {errors.filters && (
          <p id="job-filters-error" className="text-sm text-destructive">
            {errors.filters}
          </p>
        )}
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => patch({ filters: [...state.filters, { field: "", value: "" }] })}
          >
            <Plus aria-hidden className="size-4" />
            {t("jobs.wizard.options.filterAdd")}
          </Button>
        </div>
      </fieldset>

      <FormField
        name="batchSize"
        label={t("jobs.wizard.options.batchSize")}
        error={errors.batchSize}
        hint={t("jobs.wizard.options.batchHint")}
      >
        {(props) => (
          <Input
            {...props}
            type="number"
            min={1}
            max={1000}
            className="w-32"
            value={state.batchSize}
            onChange={(e) => patch({ batchSize: e.target.value })}
          />
        )}
      </FormField>

      {state.direction === "bidirectional" && (
        <div className="flex flex-col gap-4">
          <FormField
            name="conflictRule"
            label={t("jobs.wizard.options.conflict")}
            hint={t("jobs.wizard.options.conflictHint")}
            required={false}
          >
            {(props) => (
              <Select
                {...props}
                value={state.conflictRule}
                onChange={(e) => patch({ conflictRule: e.target.value as ConflictRule })}
              >
                {CONFLICT_RULES.map((rule) => (
                  <option key={rule} value={rule}>
                    {t(`jobs.wizard.options.conflictRules.${rule}`)}
                  </option>
                ))}
              </Select>
            )}
          </FormField>
          {state.conflictRule === "newest_wins" && (
            <div className="grid gap-4 md:grid-cols-2">
              <FormField
                name="sourceUpdatedField"
                label={t("jobs.wizard.options.sourceUpdated")}
                error={errors.sourceUpdatedField}
              >
                {(props) => (
                  <Input
                    {...props}
                    list={SOURCE_FIELDS_ID}
                    className="font-mono text-xs"
                    value={state.sourceUpdatedField}
                    onChange={(e) => patch({ sourceUpdatedField: e.target.value })}
                  />
                )}
              </FormField>
              <FormField
                name="targetUpdatedField"
                label={t("jobs.wizard.options.targetUpdated")}
                error={errors.targetUpdatedField}
              >
                {(props) => (
                  <Input
                    {...props}
                    list={TARGET_FIELDS_ID}
                    className="font-mono text-xs"
                    value={state.targetUpdatedField}
                    onChange={(e) => patch({ targetUpdatedField: e.target.value })}
                  />
                )}
              </FormField>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

// -- step 4 ------------------------------------------------------------------------------------

const TRIGGER_KINDS = ["manual", "schedule", "webhook"] as const;

export function TriggerStep({ state, errors, patch }: StepProps) {
  const { t } = useTranslation();
  // Keep unknown events a stored job already listens to, next to the ones the intake publishes.
  const events = [...new Set([...KNOWN_EVENT_TYPES, ...state.eventTypes])];
  return (
    <div className="flex flex-col gap-6">
      <RadioGroup
        legend={t("jobs.wizard.trigger.legend")}
        name="trigger"
        value={state.triggerKind}
        options={TRIGGER_KINDS.map((kind) => ({
          value: kind,
          label: t(`jobs.wizard.trigger.kinds.${kind}.label`),
          description: t(`jobs.wizard.trigger.kinds.${kind}.hint`),
        }))}
        onChange={(kind) => patch({ triggerKind: kind as (typeof TRIGGER_KINDS)[number] })}
      />
      {state.triggerKind === "schedule" && (
        <CronEditor value={state.cron} error={errors.cron} onChange={(cron) => patch({ cron })} />
      )}
      {state.triggerKind === "webhook" && (
        <CheckboxGroup
          legend={t("jobs.wizard.trigger.events")}
          values={state.eventTypes}
          options={events.map((event) => ({ value: event, label: event }))}
          error={errors.eventTypes}
          onChange={(eventTypes) => patch({ eventTypes })}
        />
      )}
    </div>
  );
}
