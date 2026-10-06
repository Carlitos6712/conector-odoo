import { ArrowDown, ArrowUp, Trash2 } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ExprEditor } from "@/features/mappings/ExprEditor";
import { CheckField, TextField } from "@/features/mappings/Fields";
import { IssueList } from "@/features/mappings/IssueList";
import type { FRule } from "@/features/mappings/model";
import type { Issue } from "@/features/mappings/types";

/** One rule: target field, required flag, expression builder and the findings that point at it. */
export function RuleCard({
  index,
  total,
  rule,
  issues,
  extra,
  targetListId,
  sourceListId,
  onChange,
  onMove,
  onRemove,
}: {
  index: number;
  total: number;
  rule: FRule;
  issues: readonly Issue[];
  /** Anything else the page wants to show on this rule (dry-run errors). */
  extra?: React.ReactNode;
  targetListId: string;
  sourceListId: string;
  onChange: (rule: FRule) => void;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  const n = index + 1;
  return (
    <fieldset className="flex flex-col gap-4 rounded-md border p-4">
      <legend className="px-1 text-sm font-semibold">
        {t("mappings.editor.rules.rule", { n })}
      </legend>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div className="grid flex-1 items-end gap-3 sm:grid-cols-[minmax(0,1fr)_auto]">
          <TextField
            label={t("mappings.editor.rules.target")}
            value={rule.target}
            list={targetListId}
            mono
            hint={t("mappings.editor.rules.targetHint")}
            onChange={(target) => onChange({ ...rule, target })}
          />
          <CheckField
            label={t("mappings.editor.rules.required")}
            checked={rule.required}
            onChange={(required) => onChange({ ...rule, required })}
          />
        </div>
        <div className="flex gap-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={index === 0}
            aria-label={t("mappings.editor.rules.moveUp", { n })}
            onClick={() => onMove(-1)}
          >
            <ArrowUp aria-hidden className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={index === total - 1}
            aria-label={t("mappings.editor.rules.moveDown", { n })}
            onClick={() => onMove(1)}
          >
            <ArrowDown aria-hidden className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            aria-label={t("mappings.editor.rules.remove", { n })}
            onClick={onRemove}
          >
            <Trash2 aria-hidden className="size-4" />
          </Button>
        </div>
      </div>
      <ExprEditor
        value={rule.expr}
        prefix=""
        sourceListId={sourceListId}
        onChange={(expr) => onChange({ ...rule, expr })}
      />
      <IssueList issues={issues} />
      {extra}
    </fieldset>
  );
}
