import { Play, RefreshCw } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { dryRunIssues } from "@/features/mappings/dryrun";
import { describeMappingError } from "@/features/mappings/errors";
import { SelectField } from "@/features/mappings/Fields";
import { useDryRun } from "@/features/mappings/hooks";
import { IssueList } from "@/features/mappings/IssueList";
import type { DryRunItem, Issue, MappingDoc } from "@/features/mappings/types";
import { formatCell } from "@/features/resources/format";

const SAMPLE_SIZES = [5, 10, 20, 50] as const;
const MAX_INPUT_FIELDS = 12;

function Values({ label, values }: { label: string; values: Record<string, unknown> }) {
  const { t } = useTranslation();
  const entries = Object.entries(values);
  const shown = entries.slice(0, MAX_INPUT_FIELDS);
  return (
    <dl aria-label={label} className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-xs">
      {shown.map(([key, value]) => {
        const cell = formatCell(value);
        return (
          <div key={key} className="contents">
            <dt className="font-mono text-muted-foreground">{key}</dt>
            <dd title={cell.full} className="break-words font-mono">
              {cell.text}
            </dd>
          </div>
        );
      })}
      {entries.length > shown.length && (
        <div className="col-span-2 text-muted-foreground">
          {t("mappings.dryRun.more", { count: entries.length - shown.length })}
        </div>
      )}
    </dl>
  );
}

function RecordResult({
  item,
  input,
  definition,
}: {
  item: DryRunItem;
  input: Record<string, unknown> | undefined;
  definition: MappingDoc;
}) {
  const { t } = useTranslation();
  const id = item.source_id ?? t("mappings.dryRun.noId");
  const pathOf = (target: string, step: number | null) => {
    const index = definition.rules.findIndex((rule) => rule.target === target);
    if (index < 0) return `target.${target}`;
    return step === null ? `rules[${index}]` : `rules[${index}].expr.steps[${step}]`;
  };
  const problems: Issue[] = [
    ...item.errors.map((error) => ({
      path: pathOf(error.rule_target, error.step_index),
      severity: "error" as const,
      message: error.message,
    })),
    ...item.validation,
  ];
  return (
    <div
      role="group"
      aria-label={t("mappings.dryRun.record", { id })}
      className="flex flex-col gap-3 rounded-md border p-3"
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-sm font-medium">{id}</span>
        <Badge variant={item.ok ? "success" : "destructive"}>
          {t(item.ok ? "mappings.dryRun.ok" : "mappings.dryRun.failed")}
        </Badge>
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="flex flex-col gap-1">
          <h4 className="text-sm font-medium">{t("mappings.dryRun.input")}</h4>
          {input ? (
            <Values label={t("mappings.dryRun.input")} values={input} />
          ) : (
            <p className="text-sm text-muted-foreground">{t("mappings.dryRun.inputUnavailable")}</p>
          )}
        </div>
        <div className="flex flex-col gap-1">
          <h4 className="text-sm font-medium">{t("mappings.dryRun.output")}</h4>
          {Object.keys(item.mapped_fields).length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("mappings.dryRun.noOutput")}</p>
          ) : (
            <Values label={t("mappings.dryRun.output")} values={item.mapped_fields} />
          )}
        </div>
      </div>
      {problems.length > 0 && (
        <IssueList issues={problems} label={t("mappings.dryRun.recordErrors")} />
      )}
    </div>
  );
}

/**
 * Runs the draft over live sample records and shows, per record, the input, the mapped output
 * and the rule errors. Findings are also handed to the editor (`onResult`) so it can show them
 * on the offending rule; they are keyed by the definition they were produced from.
 */
export function DryRunPanel({
  definition,
  sourceProfileId,
  targetProfileId,
  blocked,
  onResult,
}: {
  definition: MappingDoc;
  sourceProfileId: number | null;
  targetProfileId: number | null;
  /** The rules have blocking errors: the server would reject the definition. */
  blocked: boolean;
  onResult: (definitionKey: string, issues: Issue[]) => void;
}) {
  const { t } = useTranslation();
  const run = useDryRun();
  const [limit, setLimit] = useState("5");
  const [ranWith, setRanWith] = useState<string | null>(null);
  const key = JSON.stringify(definition);
  const ready = sourceProfileId !== null && targetProfileId !== null && !blocked;

  function execute() {
    if (sourceProfileId === null || targetProfileId === null) return;
    run.mutate(
      { definition, sourceProfileId, targetProfileId, limit: Number(limit) },
      {
        onSuccess: (result) => {
          setRanWith(key);
          onResult(key, dryRunIssues(definition, result.report));
        },
        onError: (error) => {
          setRanWith(key);
          onResult(key, describeMappingError(error, "dryRun").issues);
        },
      },
    );
  }

  const failure = run.error ? describeMappingError(run.error, "dryRun") : null;
  const result = run.data;
  const stale = ranWith !== null && ranWith !== key;

  return (
    <section className="flex flex-col gap-4" aria-label={t("mappings.dryRun.title")}>
      <div>
        <h2 className="text-lg font-semibold">{t("mappings.dryRun.title")}</h2>
        <p className="text-sm text-muted-foreground">{t("mappings.dryRun.description")}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <div className="w-48">
          <SelectField label={t("mappings.dryRun.limit")} value={limit} onChange={setLimit}>
            {SAMPLE_SIZES.map((size) => (
              <option key={size} value={size}>
                {size}
              </option>
            ))}
          </SelectField>
        </div>
        <Button type="button" disabled={!ready || run.isPending} onClick={execute}>
          {result || failure ? (
            <RefreshCw aria-hidden className="size-4" />
          ) : (
            <Play aria-hidden className="size-4" />
          )}
          {t(result || failure ? "mappings.dryRun.refresh" : "mappings.dryRun.run")}
        </Button>
      </div>
      {sourceProfileId === null || targetProfileId === null ? (
        <p className="text-xs text-muted-foreground">{t("mappings.dryRun.needsSides")}</p>
      ) : (
        blocked && <p className="text-xs text-muted-foreground">{t("mappings.dryRun.blocked")}</p>
      )}
      {stale && (
        <p role="status" className="text-sm text-amber-700">
          {t("mappings.dryRun.stale")}
        </p>
      )}
      {failure && (
        <div role="alert" className="flex flex-col gap-2 rounded-md border border-destructive p-3">
          <p className="text-sm font-medium text-destructive">
            {t(failure.messageKey, failure.params)}
          </p>
          {failure.detail && <p className="break-words text-sm">{failure.detail}</p>}
          <IssueList issues={failure.issues} />
        </div>
      )}
      {result && (
        <div className="flex flex-col gap-3">
          <p className="text-sm font-medium">
            {`${t("mappings.dryRun.total", { count: result.report.total })}: ${t("mappings.dryRun.okCount", { count: result.report.ok })}, ${t("mappings.dryRun.errorCount", { count: result.report.with_errors })}`}
          </p>
          {result.report.definition_issues.length > 0 && (
            <IssueList issues={result.report.definition_issues} />
          )}
          {result.report.items.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("mappings.dryRun.empty")}</p>
          ) : (
            result.report.items.map((item, index) => (
              <RecordResult
                key={item.source_id ?? index}
                item={item}
                input={item.source_id === null ? undefined : result.inputs[item.source_id]}
                definition={definition}
              />
            ))
          )}
        </div>
      )}
    </section>
  );
}
