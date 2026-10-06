import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useNavigate, useSearchParams } from "react-router-dom";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Textarea } from "@/components/ui/textarea";
import { FormField } from "@/features/connections/FormField";
import { useProfiles } from "@/features/connections/hooks";
import { describeResourceError, type DescribedResourceError } from "@/features/resources/errors";
import {
  formFromConfig,
  toInput,
  validateForm,
  type FormErrors,
  type ResourceFormState,
} from "@/features/resources/form";
import { useImportOpenApi, useResources, useSaveResource } from "@/features/resources/hooks";
import { ResourceFormFields } from "@/features/resources/ResourceFormFields";
import type { ImportReport } from "@/features/resources/types";

type SourceTab = "url" | "document";

interface Failure {
  name: string;
  error: DescribedResourceError;
}

function listEndpoint(form: ResourceFormState): string {
  const path = form.list_path || form.get_path || form.create_path || form.update_path;
  const method =
    form.list_path || form.get_path
      ? "GET"
      : form.create_path
        ? form.create_method
        : form.update_method;
  return path ? `${method} ${path}` : "—";
}

function EditCandidateDialog({
  draft,
  profiles,
  onApply,
  onClose,
}: {
  draft: ResourceFormState | null;
  profiles: Parameters<typeof ResourceFormFields>[0]["profiles"];
  onApply: (form: ResourceFormState) => void;
  onClose: () => void;
}) {
  return (
    <Dialog open={draft !== null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-3xl overflow-y-auto">
        {draft && (
          <EditCandidateForm
            key={draft.name}
            initial={draft}
            profiles={profiles}
            onApply={onApply}
            onClose={onClose}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function EditCandidateForm({
  initial,
  profiles,
  onApply,
  onClose,
}: {
  initial: ResourceFormState;
  profiles: Parameters<typeof ResourceFormFields>[0]["profiles"];
  onApply: (form: ResourceFormState) => void;
  onClose: () => void;
}) {
  const { t } = useTranslation();
  const [form, setForm] = useState(initial);
  const [errors, setErrors] = useState<FormErrors>({});
  return (
    <>
      <DialogTitle>{t("resources.import.editTitle", { name: initial.name })}</DialogTitle>
      <DialogDescription>{t("resources.import.editHint")}</DialogDescription>
      <ResourceFormFields
        form={form}
        errors={errors}
        profiles={profiles}
        lockProfile
        lockName={false}
        onChange={(patch) => {
          setForm((previous) => ({ ...previous, ...patch }));
          setErrors({});
        }}
      />
      <DialogFooter>
        <Button variant="outline" onClick={onClose}>
          {t("common.cancel")}
        </Button>
        <Button
          onClick={() => {
            const found = validateForm(form, []);
            setErrors(found);
            if (Object.keys(found).length === 0) onApply(form);
          }}
        >
          {t("resources.import.apply")}
        </Button>
      </DialogFooter>
    </>
  );
}

/** Analyses an OpenAPI document (nothing is saved), lets the admin pick and edit candidates. */
export function ImportPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const { query, canMutate } = useSession();
  const [search] = useSearchParams();
  const profiles = useProfiles();
  const importer = useImportOpenApi();
  const save = useSaveResource();

  const [profileId, setProfileId] = useState(search.get("profile") ?? "");
  const [tab, setTab] = useState<SourceTab>("url");
  const [url, setUrl] = useState("");
  const [documentText, setDocumentText] = useState("");
  const [basePath, setBasePath] = useState("");

  const [report, setReport] = useState<ImportReport | null>(null);
  const [forms, setForms] = useState<ResourceFormState[]>([]);
  const [selected, setSelected] = useState<ReadonlySet<number>>(new Set());
  const [saved, setSaved] = useState<ReadonlySet<number>>(new Set());
  const [flagged, setFlagged] = useState<ReadonlySet<number>>(new Set());
  const [blocked, setBlocked] = useState(false);
  const [failures, setFailures] = useState<Failure[]>([]);
  const [savedCount, setSavedCount] = useState(0);
  const [saving, setSaving] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);

  const restProfiles = (profiles.data ?? []).filter((p) => p.type === "rest");
  const numericProfile = profileId ? Number(profileId) : null;
  const existing = useResources(numericProfile);
  const existingNames = new Set((existing.data?.items ?? []).map((item) => item.config.name));

  if (query.isPending || profiles.isPending) return <Loading />;
  if (!canMutate) return <Navigate to="/resources" replace />;

  const source = tab === "url" ? url.trim() : documentText.trim();
  const canAnalyse = numericProfile !== null && source !== "" && !importer.isPending;

  function reset() {
    setReport(null);
    setForms([]);
    setSelected(new Set());
    setSaved(new Set());
    setFlagged(new Set());
    setBlocked(false);
    setFailures([]);
    importer.reset();
  }

  function analyse() {
    if (numericProfile === null) return;
    const extra = basePath.trim() ? { base_path: basePath.trim() } : {};
    const request =
      tab === "url" ? { url: url.trim(), ...extra } : { document: documentText, ...extra };
    reset();
    importer.mutate(
      { profileId: numericProfile, request },
      {
        onSuccess: (result) => {
          setReport(result);
          setForms(result.candidates.map((c) => formFromConfig(c, "openapi", profileId)));
        },
      },
    );
  }

  function toggle(index: number, on: boolean) {
    setSelected((previous) => {
      const next = new Set(previous);
      if (on) next.add(index);
      else next.delete(index);
      return next;
    });
  }

  const selectable = forms.map((_, i) => i).filter((i) => !saved.has(i));
  const chosen = selectable.filter((i) => selected.has(i));

  async function saveChosen() {
    if (numericProfile === null) return;
    const names = chosen.map((i) => forms[i]?.name.trim());
    const bad = new Set(
      chosen.filter((i, position) => {
        const form = forms[i];
        return (
          !form ||
          Object.keys(validateForm(form, [])).length > 0 ||
          names.indexOf(names[position]) !== position
        );
      }),
    );
    setFlagged(bad);
    setFailures([]);
    setBlocked(bad.size > 0);
    if (bad.size > 0) return;

    setSaving(true);
    const done = new Set(saved);
    const failed: Failure[] = [];
    for (const index of chosen) {
      const form = forms[index];
      if (!form) continue;
      try {
        await save.mutateAsync({ profileId: numericProfile, input: toInput(form) });
        done.add(index);
      } catch (error) {
        failed.push({ name: form.name, error: describeResourceError(error, "save") });
      }
    }
    setSaved(done);
    setSaving(false);
    setSavedCount(chosen.length - failed.length);
    setFailures(failed);
    if (failed.length === 0) navigate(`/resources?profile=${numericProfile}`);
  }

  const warnings = report?.warnings ?? [];
  const missingPagination = forms.some((f) => f.strategy === "none");
  const editingForm = editing === null ? null : (forms[editing] ?? null);

  return (
    <section className="flex max-w-5xl flex-col gap-6">
      <h1 className="text-2xl font-semibold">{t("resources.import.title")}</h1>
      <p className="text-sm text-muted-foreground">{t("resources.import.intro")}</p>

      <div className="flex max-w-xl flex-col gap-4">
        <FormField name="importProfile" label={t("resources.editor.connection")}>
          {(control) => (
            <Select
              {...control}
              value={profileId}
              onChange={(event) => {
                setProfileId(event.target.value);
                reset();
              }}
            >
              <option value="">{t("resources.editor.chooseConnection")}</option>
              {restProfiles.map((profile) => (
                <option key={profile.id} value={String(profile.id)}>
                  {profile.name}
                </option>
              ))}
            </Select>
          )}
        </FormField>
        <Tabs value={tab} onValueChange={(value) => setTab(value as SourceTab)}>
          <TabsList label={t("resources.import.sourceLabel")}>
            <TabsTrigger value="url">{t("resources.import.fromUrl")}</TabsTrigger>
            <TabsTrigger value="document">{t("resources.import.fromDocument")}</TabsTrigger>
          </TabsList>
          <TabsContent value="url">
            <FormField name="openapiUrl" label={t("resources.import.url")}>
              {(control) => (
                <Input
                  {...control}
                  type="url"
                  value={url}
                  onChange={(event) => setUrl(event.target.value)}
                />
              )}
            </FormField>
          </TabsContent>
          <TabsContent value="document">
            <FormField name="openapiDocument" label={t("resources.import.document")}>
              {(control) => (
                <Textarea
                  {...control}
                  rows={8}
                  className="font-mono"
                  value={documentText}
                  onChange={(event) => setDocumentText(event.target.value)}
                />
              )}
            </FormField>
          </TabsContent>
        </Tabs>
        <FormField
          name="basePath"
          label={t("resources.import.basePath")}
          hint={t("resources.import.basePathHint")}
          required={false}
        >
          {(control) => (
            <Input
              {...control}
              className="font-mono"
              value={basePath}
              onChange={(event) => setBasePath(event.target.value)}
            />
          )}
        </FormField>
        <div className="flex gap-2">
          <Button disabled={!canAnalyse} onClick={analyse}>
            {t(importer.isPending ? "resources.import.analysing" : "resources.import.analyse")}
          </Button>
          <Button variant="outline" asChild>
            <Link to="/resources">{t("common.cancel")}</Link>
          </Button>
        </div>
      </div>

      {importer.isError && (
        <ImportError described={describeResourceError(importer.error, "import")} />
      )}

      {report && (
        <>
          <section
            aria-label={t("resources.import.warningsTitle", { count: warnings.length })}
            className="flex flex-col gap-2 rounded-md border border-warning-soft-foreground/30 bg-warning-soft p-4 text-warning-soft-foreground"
          >
            <h2 className="font-semibold">
              {t("resources.import.warningsTitle", { count: warnings.length })}
            </h2>
            {missingPagination && (
              <p className="text-sm">{t("resources.import.manualPagination")}</p>
            )}
            {warnings.length === 0 ? (
              <p className="text-sm text-muted-foreground">{t("resources.import.noWarnings")}</p>
            ) : (
              <ul className="max-h-64 list-disc overflow-y-auto pl-5 text-sm">
                {warnings.map((warning, index) => (
                  <li key={index} className="break-words">
                    {warning}
                  </li>
                ))}
              </ul>
            )}
          </section>

          {forms.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("resources.import.noCandidates")}</p>
          ) : (
            <div className="flex flex-col gap-3">
              <Table aria-label={t("resources.import.candidates")}>
                <TableHeader>
                  <TableRow>
                    <TableHead>
                      <Checkbox
                        aria-label={t("resources.import.selectAll")}
                        checked={chosen.length === selectable.length && selectable.length > 0}
                        disabled={selectable.length === 0}
                        onChange={(event) =>
                          setSelected(event.target.checked ? new Set(selectable) : new Set())
                        }
                      />
                    </TableHead>
                    <TableHead>{t("resources.columns.name")}</TableHead>
                    <TableHead>{t("resources.columns.endpoint")}</TableHead>
                    <TableHead>{t("resources.columns.pagination")}</TableHead>
                    <TableHead>{t("resources.import.status")}</TableHead>
                    <TableHead>
                      <span className="sr-only">{t("resources.columns.actions")}</span>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {forms.map((form, index) => {
                    const original = report.candidates[index]?.name ?? form.name;
                    const own = warnings.filter((w) => w.startsWith(`${original}:`)).length;
                    const done = saved.has(index);
                    return (
                      <TableRow key={index}>
                        <TableCell>
                          <Checkbox
                            aria-label={t("resources.import.select", { name: form.name })}
                            checked={selected.has(index) && !done}
                            disabled={done}
                            onChange={(event) => toggle(index, event.target.checked)}
                          />
                        </TableCell>
                        <TableCell>
                          <div className="font-mono text-xs font-medium">{form.name}</div>
                          {form.label && form.label !== form.name && (
                            <div className="text-muted-foreground">{form.label}</div>
                          )}
                        </TableCell>
                        <TableCell className="break-all font-mono text-xs">
                          {listEndpoint(form)}
                        </TableCell>
                        <TableCell>
                          {form.strategy === "none" ? (
                            <Badge variant="outline">{t("resources.import.noPagination")}</Badge>
                          ) : (
                            <Badge>{t(`resources.pagination.${form.strategy}`)}</Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {own > 0 && (
                              <Badge variant="outline">
                                {t("resources.import.warningCount", { count: own })}
                              </Badge>
                            )}
                            {existingNames.has(form.name.trim()) && !done && (
                              <Badge variant="outline">{t("resources.import.exists")}</Badge>
                            )}
                            {flagged.has(index) && (
                              <Badge variant="destructive">{t("resources.import.review")}</Badge>
                            )}
                            {done && <Badge variant="success">{t("resources.import.saved")}</Badge>}
                          </div>
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={done}
                            aria-label={t("resources.import.edit", { name: form.name })}
                            onClick={() => setEditing(index)}
                          >
                            {t("resources.import.editButton")}
                          </Button>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              {blocked && (
                <p role="alert" className="text-sm text-destructive">
                  {t("resources.import.blocked")}
                </p>
              )}
              {failures.length > 0 && (
                <div role="alert" className="text-sm text-destructive">
                  <p>
                    {t("resources.import.partial", { saved: savedCount, failed: failures.length })}
                  </p>
                  <ul className="list-disc pl-5">
                    {failures.map(({ name, error }) => (
                      <li key={name} className="break-words">
                        <span className="font-mono">{name}</span>:{" "}
                        {t(error.messageKey, error.params)}
                        {error.detail ? ` (${error.detail})` : ""}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              <div>
                <Button disabled={chosen.length === 0 || saving} onClick={() => void saveChosen()}>
                  {t("resources.import.saveSelected", { count: chosen.length })}
                </Button>
              </div>
            </div>
          )}
        </>
      )}

      <EditCandidateDialog
        draft={editingForm}
        profiles={restProfiles}
        onClose={() => setEditing(null)}
        onApply={(form) => {
          setForms((previous) => previous.map((f, i) => (i === editing ? form : f)));
          setFlagged((previous) => {
            const next = new Set(previous);
            if (editing !== null) next.delete(editing);
            return next;
          });
          setEditing(null);
        }}
      />
    </section>
  );
}

function ImportError({ described }: { described: DescribedResourceError }) {
  const { t } = useTranslation();
  return (
    <div role="alert" className="flex flex-col gap-1 text-sm">
      <p className="text-destructive">{t(described.messageKey, described.params)}</p>
      {described.detail && <p className="break-words text-muted-foreground">{described.detail}</p>}
    </div>
  );
}
