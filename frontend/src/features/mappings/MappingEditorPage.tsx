import { ArrowLeft, History, Lightbulb, Plus, Save } from "lucide-react";
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, Navigate, useParams } from "react-router-dom";
import { useSession } from "@/auth/useSession";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import { useProfiles } from "@/features/connections/hooks";
import { DryRunPanel } from "@/features/mappings/DryRunPanel";
import { describeMappingError } from "@/features/mappings/errors";
import { TextField } from "@/features/mappings/Fields";
import { hintsFor, hintToIssue, issuesForRule } from "@/features/mappings/hints";
import { useMapping, useSaveMapping, useSuggest } from "@/features/mappings/hooks";
import { IssueList } from "@/features/mappings/IssueList";
import { MappingReadOnlyView } from "@/features/mappings/MappingReadOnlyView";
import {
  definitionFromState,
  emptyState,
  mergeSuggestion,
  moveItem,
  newRule,
  removeAt,
  replaceAt,
  stateFromDefinition,
  type EditorState,
} from "@/features/mappings/model";
import { RuleCard } from "@/features/mappings/RuleCard";
import { SidePicker, useSideSchema } from "@/features/mappings/SidePicker";
import type { Issue, StoredMapping } from "@/features/mappings/types";
import { UnsavedChangesDialog, useUnsavedGuard } from "@/features/mappings/useUnsavedGuard";

const SOURCE_FIELDS = "mapping-source-fields";
const TARGET_FIELDS = "mapping-target-fields";

/** The definition as it would be sent: this is also what "unsaved changes" compares. */
const snapshot = (state: EditorState) => definitionFromState({ ...state, name: state.name.trim() });

interface SuggestNote {
  added: number;
  unmatchedSource: string[];
  unmatchedTarget: string[];
}

function MappingEditor({ initial }: { initial: StoredMapping | null }) {
  const { t } = useTranslation();
  const profiles = useProfiles();
  const save = useSaveMapping();
  const suggest = useSuggest();

  const [start] = useState<EditorState>(() =>
    initial ? stateFromDefinition(initial.definition) : emptyState(),
  );
  const [state, setState] = useState<EditorState>(start);
  const [baseline, setBaseline] = useState(() => JSON.stringify(snapshot(start)));
  const [savedName, setSavedName] = useState<string | null>(initial?.name ?? null);
  const [sourceProfile, setSourceProfile] = useState("");
  const [targetProfile, setTargetProfile] = useState("");
  const [notice, setNotice] = useState<{ version: number; created: boolean } | null>(null);
  const [suggestNote, setSuggestNote] = useState<SuggestNote | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [dry, setDry] = useState<{ key: string; issues: Issue[] } | null>(null);

  const sourceSchema = useSideSchema(sourceProfile, state.sourceResource);
  const targetSchema = useSideSchema(targetProfile, state.targetResource);

  const currentKey = JSON.stringify(snapshot(state));
  const dirty = currentKey !== baseline;
  const guard = useUnsavedGuard(dirty);

  const hints = useMemo(
    () => hintsFor(state, { sourceFields: sourceSchema.fields, targetFields: targetSchema.fields }),
    [state, sourceSchema.fields, targetSchema.fields],
  );
  const hintIssues: Issue[] = hints.map((hint) =>
    hintToIssue(hint, t(`mappings.hints.${hint.code}`, hint.params)),
  );
  const failure = save.error ? describeMappingError(save.error, "save") : null;
  const saveIssues: Issue[] = [...(failure?.issues ?? []), ...(save.data?.warnings ?? [])];
  const generalIssues = saveIssues.filter((issue) => !issue.path.startsWith("rules["));
  // Dry-run findings describe the definition they ran on; once it changes they are stale.
  const dryIssues = dry && dry.key === currentKey ? dry.issues : [];
  const serverIssues: Issue[] = [...saveIssues, ...dryIssues];
  const unmappedRequired = hintIssues.filter((issue) => issue.path.startsWith("target."));

  const editing = savedName !== null;
  const hasBlockingHint = hints.some((hint) => hint.severity === "error");
  const complete =
    state.name.trim() !== "" && state.sourceResource !== "" && state.targetResource !== "";
  const canSave = complete && !hasBlockingHint && !save.isPending;
  const canSuggest =
    sourceProfile !== "" &&
    targetProfile !== "" &&
    state.sourceResource !== "" &&
    state.targetResource !== "";

  function change(next: EditorState) {
    setState(next);
    if (save.isError || save.data) save.reset();
  }

  function submit() {
    const definition = snapshot(state);
    save.mutate(
      {
        name: definition.name,
        definition,
        sourceProfileId: sourceProfile ? Number(sourceProfile) : undefined,
        targetProfileId: targetProfile ? Number(targetProfile) : undefined,
      },
      {
        onSuccess: (result) => {
          setBaseline(JSON.stringify(definition));
          setSavedName(definition.name);
          setNotice({ version: result.mapping.version, created: result.created });
        },
      },
    );
  }

  function requestSuggestion() {
    suggest.mutate(
      {
        sourceProfileId: Number(sourceProfile),
        sourceResource: state.sourceResource,
        targetProfileId: Number(targetProfile),
        targetResource: state.targetResource,
      },
      {
        onSuccess: (result) => {
          const merged = mergeSuggestion(state, stateFromDefinition(result.definition));
          change(merged.state);
          setSuggestNote({
            added: merged.added,
            unmatchedSource: result.unmatched_source,
            unmatchedTarget: result.unmatched_target,
          });
        },
      },
    );
  }

  const suggestFailure = suggest.error ? describeMappingError(suggest.error, "suggest") : null;
  const backTo = "/mappings";

  return (
    <section className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {t(editing ? "mappings.editor.titleEdit" : "mappings.editor.titleCreate")}
        </h1>
        <div className="flex flex-wrap gap-2">
          {savedName && (
            <Button variant="outline" asChild>
              <Link to={`/mappings/${encodeURIComponent(savedName)}/versions`}>
                <History aria-hidden className="size-4" />
                {t("mappings.editor.history")}
              </Link>
            </Button>
          )}
          <Button variant="outline" asChild>
            <Link to={backTo}>
              <ArrowLeft aria-hidden className="size-4" />
              {t("mappings.versions.back")}
            </Link>
          </Button>
        </div>
      </div>

      <div className="max-w-md">
        <TextField
          label={t("mappings.editor.name")}
          value={state.name}
          readOnly={editing}
          mono
          hint={t(editing ? "mappings.editor.nameLocked" : "mappings.editor.nameHint")}
          onChange={(name) => change({ ...state, name })}
        />
      </div>

      <div className="grid gap-8 lg:grid-cols-2">
        <SidePicker
          side="source"
          profiles={profiles.data ?? []}
          profileId={sourceProfile}
          resource={state.sourceResource}
          schema={sourceSchema}
          fieldsListId={SOURCE_FIELDS}
          onProfile={setSourceProfile}
          onResource={(sourceResource) => change({ ...state, sourceResource })}
        />
        <SidePicker
          side="target"
          profiles={profiles.data ?? []}
          profileId={targetProfile}
          resource={state.targetResource}
          schema={targetSchema}
          fieldsListId={TARGET_FIELDS}
          onProfile={setTargetProfile}
          onResource={(targetResource) => change({ ...state, targetResource })}
        />
      </div>

      <div className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">{t("mappings.editor.rules.heading")}</h2>
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              disabled={!canSuggest || suggest.isPending}
              onClick={requestSuggestion}
            >
              <Lightbulb aria-hidden className="size-4" />
              {t("mappings.editor.suggest.action")}
            </Button>
            <Button
              type="button"
              variant="outline"
              onClick={() => change({ ...state, rules: [...state.rules, newRule()] })}
            >
              <Plus aria-hidden className="size-4" />
              {t("mappings.editor.rules.add")}
            </Button>
          </div>
        </div>
        {!canSuggest && (
          <p className="text-xs text-muted-foreground">{t("mappings.editor.suggest.needsSides")}</p>
        )}
        {suggestFailure && (
          <p role="alert" className="text-sm text-destructive">
            {t(suggestFailure.messageKey, suggestFailure.params)}
          </p>
        )}
        {suggestNote && (
          <div role="status" className="rounded-md border p-3 text-sm">
            <p>
              {suggestNote.added === 0
                ? t("mappings.editor.suggest.none")
                : t("mappings.editor.suggest.added", { count: suggestNote.added })}
            </p>
            {suggestNote.unmatchedSource.length > 0 && (
              <p className="text-muted-foreground">
                {t("mappings.editor.suggest.unmatchedSource", {
                  fields: suggestNote.unmatchedSource.join(", "),
                })}
              </p>
            )}
            {suggestNote.unmatchedTarget.length > 0 && (
              <p className="text-muted-foreground">
                {t("mappings.editor.suggest.unmatchedTarget", {
                  fields: suggestNote.unmatchedTarget.join(", "),
                })}
              </p>
            )}
          </div>
        )}
        {unmappedRequired.length > 0 && (
          <div className="rounded-md border border-warning-soft-foreground/30 bg-warning-soft p-3 text-warning-soft-foreground">
            <p className="mb-1 text-sm font-medium">{t("mappings.editor.rules.unmapped")}</p>
            <IssueList issues={unmappedRequired} />
          </div>
        )}
        {state.rules.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("mappings.editor.rules.empty")}</p>
        ) : (
          <div className="flex flex-col gap-4">
            {state.rules.map((rule, index) => (
              <RuleCard
                key={rule.key}
                index={index}
                total={state.rules.length}
                rule={rule}
                issues={[
                  ...issuesForRule(hintIssues, index),
                  ...issuesForRule(serverIssues, index),
                ]}
                targetListId={TARGET_FIELDS}
                sourceListId={SOURCE_FIELDS}
                onChange={(next) =>
                  change({ ...state, rules: replaceAt(state.rules, index, next) })
                }
                onMove={(delta) => change({ ...state, rules: moveItem(state.rules, index, delta) })}
                onRemove={() => change({ ...state, rules: removeAt(state.rules, index) })}
              />
            ))}
          </div>
        )}
      </div>

      <DryRunPanel
        definition={snapshot(state)}
        sourceProfileId={sourceProfile ? Number(sourceProfile) : null}
        targetProfileId={targetProfile ? Number(targetProfile) : null}
        blocked={hasBlockingHint || state.sourceResource === "" || state.targetResource === ""}
        onResult={(key, issues) => setDry({ key, issues })}
      />

      <div className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-3">
          <Button type="button" disabled={!canSave} onClick={submit}>
            <Save aria-hidden className="size-4" />
            {t("mappings.editor.save.action")}
          </Button>
          <Button
            type="button"
            variant="ghost"
            aria-expanded={showJson}
            onClick={() => setShowJson((open) => !open)}
          >
            {t(showJson ? "mappings.editor.json.hide" : "mappings.editor.json.show")}
          </Button>
          {!complete && (
            <p className="text-xs text-muted-foreground">{t("mappings.editor.save.incomplete")}</p>
          )}
        </div>
        {notice && (
          <p role="status" className="text-sm">
            {t(notice.created ? "mappings.editor.save.saved" : "mappings.editor.save.unchanged", {
              version: notice.version,
            })}
          </p>
        )}
        {failure && (
          <div
            role="alert"
            className="flex flex-col gap-2 rounded-md border border-destructive p-3"
          >
            <p className="text-sm font-medium text-destructive">
              {t(failure.messageKey, failure.params)}
            </p>
            {failure.detail && <p className="break-words text-sm">{failure.detail}</p>}
            <IssueList issues={generalIssues} />
          </div>
        )}
        {!failure && generalIssues.length > 0 && (
          <div className="rounded-md border p-3">
            <p className="mb-1 text-sm font-medium">{t("mappings.editor.save.warnings")}</p>
            <IssueList issues={generalIssues} />
          </div>
        )}
        {showJson && (
          <section aria-label={t("mappings.editor.json.title")}>
            <pre className="max-h-[32rem] overflow-auto rounded-md border bg-muted p-3 text-xs">
              {JSON.stringify(snapshot(state), null, 2)}
            </pre>
          </section>
        )}
      </div>

      <UnsavedChangesDialog open={guard.pending} onStay={guard.stay} onLeave={guard.leave} />
    </section>
  );
}

export function MappingEditorPage() {
  const { t } = useTranslation();
  const { name } = useParams();
  const { query, canMutate } = useSession();
  const stored = useMapping(name ?? null);

  if (query.isPending) return <Loading />;
  if (name === undefined) {
    return canMutate ? <MappingEditor initial={null} /> : <Navigate to="/mappings" replace />;
  }
  if (stored.isPending) return <Loading />;
  if (stored.isError) {
    const described = describeMappingError(stored.error, "load");
    return (
      <div role="alert" className="flex flex-col items-start gap-3 p-6">
        <p className="text-destructive">{t(described.messageKey, described.params)}</p>
        <Button variant="outline" asChild>
          <Link to="/mappings">{t("mappings.versions.back")}</Link>
        </Button>
      </div>
    );
  }
  if (!canMutate) return <MappingReadOnlyView stored={stored.data} />;
  return <MappingEditor key={name} initial={stored.data} />;
}
