import { useState, type FormEvent } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useProfiles } from "@/features/connections/hooks";
import type { Profile } from "@/features/connections/types";
import { describeResourceError } from "@/features/resources/errors";
import {
  emptyForm,
  formFromConfig,
  serverFieldToForm,
  toInput,
  validateForm,
  type FormErrors,
  type ResourceFormState,
} from "@/features/resources/form";
import { useResource, useResources, useSaveResource } from "@/features/resources/hooks";
import { PreviewPanel } from "@/features/resources/PreviewPanel";
import { ResourceFormFields } from "@/features/resources/ResourceFormFields";
import type { StoredResource } from "@/features/resources/types";

function ResourceEditor({
  profiles,
  stored,
  defaultProfileId,
}: {
  profiles: readonly Profile[];
  stored?: StoredResource;
  defaultProfileId: string;
}) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const save = useSaveResource();
  const editing = stored !== undefined;
  const [form, setForm] = useState<ResourceFormState>(() =>
    stored
      ? formFromConfig(stored.config, stored.source, String(stored.profile_id))
      : emptyForm(defaultProfileId),
  );
  const [clientErrors, setClientErrors] = useState<FormErrors>({});
  const [showPreview, setShowPreview] = useState(false);

  const profileId = form.profileId ? Number(form.profileId) : null;
  const existing = useResources(editing ? null : profileId);
  const existingNames = (existing.data?.items ?? []).map((item) => item.config.name);

  const failure = save.error ? describeResourceError(save.error, "save") : null;
  const serverErrors: FormErrors = failure
    ? Object.fromEntries(
        Object.entries(failure.fieldErrors).map(([field, key]) => [serverFieldToForm(field), key]),
      )
    : {};
  const errors = { ...serverErrors, ...clientErrors };

  function change(patch: Partial<ResourceFormState>) {
    setForm((previous) => ({ ...previous, ...patch }));
    setClientErrors({});
    if (save.isError) save.reset();
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    const found = validateForm(form, editing ? [] : existingNames);
    setClientErrors(found);
    if (Object.keys(found).length > 0) return;
    save.mutate(
      { profileId: Number(form.profileId), input: toInput(form) },
      { onSuccess: () => navigate(`/resources?profile=${form.profileId}`) },
    );
  }

  const back = form.profileId ? `/resources?profile=${form.profileId}` : "/resources";
  return (
    <section className="flex max-w-3xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">
        {t(editing ? "resources.editor.titleEdit" : "resources.editor.titleCreate")}
      </h1>
      <form noValidate onSubmit={submit} className="flex flex-col gap-6">
        <ResourceFormFields
          form={form}
          errors={errors}
          onChange={change}
          profiles={profiles}
          lockIdentity={editing}
        />
        {failure && (
          <div role="alert" className="text-sm text-destructive">
            <p>{t(failure.messageKey, failure.params)}</p>
            {failure.detail && <p className="mt-1 break-words">{failure.detail}</p>}
          </div>
        )}
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending}>
            {t(save.isPending ? "resources.editor.saving" : "resources.editor.save")}
          </Button>
          <Button variant="outline" asChild>
            <Link to={back}>{t("common.cancel")}</Link>
          </Button>
        </div>
      </form>
      {editing && profileId !== null && (
        <Card>
          <CardHeader>
            <CardTitle>{t("resources.editor.previewTitle")}</CardTitle>
            <CardDescription>{t("resources.editor.previewHint")}</CardDescription>
          </CardHeader>
          <CardContent>
            {showPreview ? (
              <PreviewPanel profileId={profileId} name={form.name} />
            ) : (
              <Button variant="outline" onClick={() => setShowPreview(true)}>
                {t("resources.editor.runPreview")}
              </Button>
            )}
          </CardContent>
        </Card>
      )}
    </section>
  );
}

/** Route wrapper: admins only; loads the profiles and, when editing, the saved resource. */
export function ResourceEditorPage() {
  const { t } = useTranslation();
  const { query, canMutate } = useSession();
  const params = useParams();
  const [search] = useSearchParams();
  const editing = params.name !== undefined;
  const profileId = editing ? Number(params.profileId) : null;
  const profiles = useProfiles();
  const resource = useResource(
    canMutate ? profileId : null,
    canMutate ? (params.name ?? null) : null,
  );

  if (query.isPending) return <Loading />;
  if (!canMutate) return <Navigate to="/resources" replace />;
  if (profiles.isPending || (editing && resource.isPending)) return <Loading />;
  const failed = profiles.isError ? profiles.error : resource.isError ? resource.error : null;
  if (failed) {
    const described = describeResourceError(failed, "load");
    return (
      <div role="alert" className="flex flex-col gap-3 p-6">
        <p className="text-destructive">{t(described.messageKey, described.params)}</p>
      </div>
    );
  }
  const restProfiles = profiles.data?.filter((p) => p.type === "rest") ?? [];
  return (
    <ResourceEditor
      key={editing ? `${params.profileId}/${params.name}` : "new"}
      profiles={restProfiles}
      stored={editing ? resource.data : undefined}
      defaultProfileId={search.get("profile") ?? ""}
    />
  );
}
