import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import { TextField } from "@/features/mappings/Fields";
import type { Profile } from "@/features/connections/types";
import { describeResourceError } from "@/features/resources/errors";
import { useDiscoverModels, useResources } from "@/features/resources/hooks";
import { SchemaTable } from "@/features/resources/PreviewPanel";
import type { FieldSpec } from "@/features/resources/types";

export interface SchemaState {
  fields: readonly FieldSpec[] | undefined;
  isLoading: boolean;
  error: unknown;
  retry: () => void;
}

/** Odoo model name: applied when the input loses focus, so typing never fires a request. */
function ModelInput({
  profileId,
  value,
  onCommit,
  listId,
}: {
  profileId: number;
  value: string;
  onCommit: (value: string) => void;
  listId: string;
}) {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const models = useDiscoverModels(profileId, canMutate);
  const [draft, setDraft] = useState<string | null>(null);
  const commit = () => {
    if (draft !== null) onCommit(draft.trim());
    setDraft(null);
  };
  return (
    <div>
      <TextField
        label={t("mappings.editor.side.model")}
        value={draft ?? value}
        list={listId}
        mono
        hint={t("mappings.editor.side.modelHint")}
        onChange={setDraft}
        onCommit={commit}
      />
      <datalist id={listId}>
        {(models.data ?? []).map((model) => (
          <option key={model.name} value={model.name} label={model.label} />
        ))}
      </datalist>
    </div>
  );
}

/**
 * One side of a mapping: a connection plus the REST resource or Odoo model on it. Shows the
 * fields of the chosen resource and publishes their names in a `<datalist>` for the rule inputs.
 */
export function SidePicker({
  side,
  profiles,
  profileId,
  resource,
  schema,
  fieldsListId,
  onProfile,
  onResource,
}: {
  side: "source" | "target";
  profiles: readonly Profile[];
  profileId: string;
  resource: string;
  schema: SchemaState;
  fieldsListId: string;
  onProfile: (profileId: string) => void;
  onResource: (resource: string) => void;
}) {
  const { t } = useTranslation();
  const profile = profiles.find((p) => String(p.id) === profileId) ?? null;
  const catalog = useResources(profile?.type === "rest" ? profile.id : null);
  const names = (catalog.data?.items ?? []).map((item) => item.config.name);
  const options = resource && !names.includes(resource) ? [resource, ...names] : names;
  const described = schema.error ? describeResourceError(schema.error, "preview") : null;

  return (
    <div
      role="group"
      aria-label={t(`mappings.editor.side.${side}`)}
      className="flex flex-col gap-3"
    >
      <h2 className="text-lg font-semibold">{t(`mappings.editor.side.${side}`)}</h2>
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={`${side}-profile`}>{t("mappings.editor.side.connection")}</Label>
        <Select
          id={`${side}-profile`}
          value={profileId}
          onChange={(event) => onProfile(event.target.value)}
        >
          <option value="">{t("mappings.editor.side.connectionPick")}</option>
          {profiles.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </Select>
      </div>
      {profile?.type === "rest" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor={`${side}-resource`}>{t("mappings.editor.side.resource")}</Label>
          <Select
            id={`${side}-resource`}
            value={resource}
            onChange={(event) => onResource(event.target.value)}
          >
            <option value="">{t("mappings.editor.side.resourcePick")}</option>
            {options.map((name) => (
              <option key={name} value={name}>
                {name}
              </option>
            ))}
          </Select>
        </div>
      )}
      {profile?.type === "odoo" && (
        <ModelInput
          profileId={profile.id}
          value={resource}
          onCommit={onResource}
          listId={`${side}-models`}
        />
      )}
      {!profile && (
        <p className="text-sm text-muted-foreground">
          {t(resource ? "mappings.editor.side.pickConnection" : "mappings.editor.side.pickFirst")}
        </p>
      )}
      {profile && resource && schema.isLoading && <Loading />}
      {described && (
        <div role="alert" className="flex flex-col items-start gap-2 text-sm">
          <p className="text-destructive">{t(described.messageKey, described.params)}</p>
          {described.detail && (
            <p className="break-words text-muted-foreground">{described.detail}</p>
          )}
          <Button type="button" variant="outline" size="sm" onClick={schema.retry}>
            {t("common.retry")}
          </Button>
        </div>
      )}
      {schema.fields && (
        <>
          <datalist id={fieldsListId}>
            {schema.fields.map((field) => (
              <option key={field.name} value={field.name} />
            ))}
          </datalist>
          <div className="max-h-72 overflow-y-auto">
            <SchemaTable
              fields={schema.fields}
              label={t(`mappings.editor.side.fieldsOf.${side}`)}
            />
          </div>
        </>
      )}
    </div>
  );
}
