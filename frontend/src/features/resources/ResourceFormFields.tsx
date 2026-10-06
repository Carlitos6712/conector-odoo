import type { ChangeEvent } from "react";
import { useTranslation } from "react-i18next";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { FormField } from "@/features/connections/FormField";
import type { Profile } from "@/features/connections/types";
import {
  CREATE_METHODS,
  STRATEGIES,
  UPDATE_METHODS,
  type FormErrors,
  type ResourceFormState,
} from "@/features/resources/form";

interface FieldsProps {
  form: ResourceFormState;
  errors: FormErrors;
  onChange: (patch: Partial<ResourceFormState>) => void;
}

type StringKey = {
  [K in keyof ResourceFormState]: ResourceFormState[K] extends string ? K : never;
}[keyof ResourceFormState];

/** A text control bound to one string field of the form, with label, hint and inline error. */
function TextField({
  field,
  label,
  hint,
  required = false,
  disabled,
  mono = true,
  type = "text",
  props,
}: {
  field: StringKey;
  label: string;
  hint?: string;
  required?: boolean;
  disabled?: boolean;
  mono?: boolean;
  type?: "text" | "number";
  props: FieldsProps;
}) {
  const { t } = useTranslation();
  const { form, errors, onChange } = props;
  const error = errors[field];
  return (
    <FormField
      name={field}
      label={label}
      hint={hint}
      required={required}
      error={error ? t(error) : undefined}
    >
      {(control) => (
        <Input
          {...control}
          type={type}
          className={mono ? "font-mono" : undefined}
          value={form[field]}
          disabled={disabled}
          onChange={(event: ChangeEvent<HTMLInputElement>) =>
            onChange({ [field]: event.target.value })
          }
        />
      )}
    </FormField>
  );
}

/** Only the parameters the chosen strategy actually uses are shown. */
export function PaginationFields(props: FieldsProps) {
  const { t } = useTranslation();
  const { form, errors, onChange } = props;
  const shared = (field: StringKey, label: string, required = true, hint?: string) => (
    <TextField field={field} label={label} required={required} hint={hint} props={props} />
  );
  return (
    <fieldset className="flex flex-col gap-4">
      <legend className="mb-2 text-base font-semibold">
        {t("resources.editor.pagination.title")}
      </legend>
      <FormField
        name="strategy"
        label={t("resources.editor.pagination.strategy")}
        hint={t(`resources.editor.pagination.hints.${form.strategy}`)}
        error={errors.strategy ? t(errors.strategy) : undefined}
      >
        {(control) => (
          <Select
            {...control}
            value={form.strategy}
            onChange={(event) =>
              onChange({ strategy: event.target.value as ResourceFormState["strategy"] })
            }
          >
            {STRATEGIES.map((strategy) => (
              <option key={strategy} value={strategy}>
                {t(`resources.pagination.${strategy}`)}
              </option>
            ))}
          </Select>
        )}
      </FormField>
      {form.strategy === "page" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {shared("page_param", t("resources.editor.pagination.pageParam"))}
          {shared("size_param", t("resources.editor.pagination.sizeParam"))}
          <TextField
            field="first_page"
            label={t("resources.editor.pagination.firstPage")}
            type="number"
            required
            props={props}
          />
          {shared(
            "total_pages_path",
            t("resources.editor.pagination.totalPagesPath"),
            false,
            t("resources.editor.pagination.pathHint"),
          )}
        </div>
      )}
      {form.strategy === "offset" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {shared("offset_param", t("resources.editor.pagination.offsetParam"))}
          {shared("limit_param", t("resources.editor.pagination.limitParam"))}
          {shared(
            "total_path",
            t("resources.editor.pagination.totalPath"),
            false,
            t("resources.editor.pagination.pathHint"),
          )}
        </div>
      )}
      {form.strategy === "cursor" && (
        <div className="grid gap-4 sm:grid-cols-2">
          {shared("cursor_param", t("resources.editor.pagination.cursorParam"))}
          {shared("limit_param", t("resources.editor.pagination.limitParam"), false)}
          {shared(
            "next_cursor_path",
            t("resources.editor.pagination.nextCursorPath"),
            true,
            t("resources.editor.pagination.pathHint"),
          )}
        </div>
      )}
      {form.strategy !== "none" && (
        <div className="max-w-xs">
          <TextField
            field="max_pages"
            label={t("resources.editor.pagination.maxPages")}
            hint={t("resources.editor.pagination.maxPagesHint")}
            type="number"
            required
            props={props}
          />
        </div>
      )}
    </fieldset>
  );
}

function EndpointRow({
  props,
  field,
  label,
  hint,
  methodField,
  methods,
}: {
  props: FieldsProps;
  field: "list_path" | "get_path" | "create_path" | "update_path" | "delete_path";
  label: string;
  hint?: string;
  methodField?: "create_method" | "update_method";
  methods?: readonly string[];
}) {
  const { t } = useTranslation();
  const { form, onChange } = props;
  return (
    <div className="grid gap-3 sm:grid-cols-[1fr_8rem]">
      <TextField field={field} label={label} hint={hint} props={props} />
      {methodField && methods && (
        <FormField name={methodField} label={t("resources.editor.method")} required={false}>
          {(control) => (
            <Select
              {...control}
              value={form[methodField]}
              onChange={(event) => onChange({ [methodField]: event.target.value })}
            >
              {methods.map((method) => (
                <option key={method} value={method}>
                  {method}
                </option>
              ))}
            </Select>
          )}
        </FormField>
      )}
    </div>
  );
}

/** The whole resource form; the page decides what happens on save. */
export function ResourceFormFields({
  profiles,
  lockProfile,
  lockName,
  ...props
}: FieldsProps & { profiles: readonly Profile[]; lockProfile: boolean; lockName: boolean }) {
  const { t } = useTranslation();
  const { form, errors, onChange } = props;
  return (
    <div className="flex flex-col gap-8">
      <section className="grid gap-4 sm:grid-cols-2">
        <FormField
          name="profileId"
          label={t("resources.editor.connection")}
          error={errors.profileId ? t(errors.profileId) : undefined}
        >
          {(control) => (
            <Select
              {...control}
              value={form.profileId}
              disabled={lockProfile}
              onChange={(event) => onChange({ profileId: event.target.value })}
            >
              <option value="">{t("resources.editor.chooseConnection")}</option>
              {profiles.map((profile) => (
                <option key={profile.id} value={String(profile.id)}>
                  {profile.name}
                </option>
              ))}
            </Select>
          )}
        </FormField>
        <TextField
          field="name"
          label={t("resources.editor.name")}
          hint={t("resources.editor.nameHint")}
          required
          disabled={lockName}
          props={props}
        />
        <TextField field="label" label={t("resources.editor.label")} mono={false} props={props} />
      </section>

      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">{t("resources.editor.endpoints")}</legend>
        <p className="text-sm text-muted-foreground">{t("resources.editor.endpointsHint")}</p>
        <EndpointRow props={props} field="list_path" label={t("resources.editor.listPath")} />
        <EndpointRow props={props} field="get_path" label={t("resources.editor.getPath")} />
        <EndpointRow
          props={props}
          field="create_path"
          label={t("resources.editor.createPath")}
          methodField="create_method"
          methods={CREATE_METHODS}
        />
        <EndpointRow
          props={props}
          field="update_path"
          label={t("resources.editor.updatePath")}
          methodField="update_method"
          methods={UPDATE_METHODS}
        />
        <EndpointRow props={props} field="delete_path" label={t("resources.editor.deletePath")} />
      </fieldset>

      <fieldset className="grid gap-4 sm:grid-cols-2">
        <legend className="mb-2 text-base font-semibold">{t("resources.editor.shape")}</legend>
        <TextField
          field="id_field"
          label={t("resources.editor.idField")}
          hint={t("resources.editor.idFieldHint")}
          required
          props={props}
        />
        <TextField
          field="items_path"
          label={t("resources.editor.itemsPath")}
          hint={t("resources.editor.itemsPathHint")}
          props={props}
        />
        <TextField
          field="item_path"
          label={t("resources.editor.itemPath")}
          hint={t("resources.editor.itemPathHint")}
          props={props}
        />
      </fieldset>

      {form.strategy === "none" && form.source === "openapi" && (
        <p
          role="note"
          className="rounded-md border border-warning-soft-foreground/30 bg-warning-soft p-3 text-sm text-warning-soft-foreground"
        >
          {t("resources.editor.pagination.openapiMissing")}
        </p>
      )}
      <PaginationFields {...props} />

      <fieldset className="flex flex-col gap-4">
        <legend className="mb-2 text-base font-semibold">{t("resources.editor.filters")}</legend>
        <TextField
          field="since_param"
          label={t("resources.editor.sinceParam")}
          hint={t("resources.editor.sinceParamHint")}
          props={props}
        />
        <FormField
          name="filter_text"
          label={t("resources.editor.filterMap")}
          hint={t("resources.editor.filterMapHint")}
          required={false}
          error={errors.filter_text ? t(errors.filter_text) : undefined}
        >
          {(control) => (
            <Textarea
              {...control}
              className="font-mono"
              value={form.filter_text}
              onChange={(event) => onChange({ filter_text: event.target.value })}
            />
          )}
        </FormField>
      </fieldset>
    </div>
  );
}
