import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { CheckField, SelectField, TextField } from "@/features/mappings/Fields";
import {
  changeExprKind,
  defaultExpr,
  defaultStep,
  EXPR_KINDS,
  moveItem,
  removeAt,
  replaceAt,
  STEP_TYPES,
  type ExprKind,
  type FExpr,
  type FStep,
  type StepType,
} from "@/features/mappings/model";
import type { LookupMissing } from "@/features/mappings/types";

interface Shared {
  /** Prepended to every control name so nested editors stay distinguishable (`Parte 1 · `). */
  prefix: string;
  /** `<datalist>` id with the source field names, for the source inputs. */
  sourceListId: string;
}

/** Up / down / remove for one entry of an ordered list; keyboard friendly, no dragging. */
function ListButtons({
  prefix,
  noun,
  n,
  first,
  last,
  onMove,
  onRemove,
}: {
  prefix: string;
  noun: "part" | "step" | "alternative" | "row";
  n: number;
  first: boolean;
  last: boolean;
  onMove: (delta: -1 | 1) => void;
  onRemove: () => void;
}) {
  const { t } = useTranslation();
  return (
    <div className="flex shrink-0 gap-1">
      {noun !== "row" && (
        <>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={first}
            aria-label={`${prefix}${t(`mappings.editor.move.up.${noun}`, { n })}`}
            onClick={() => onMove(-1)}
          >
            <ArrowUp aria-hidden className="size-4" />
          </Button>
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={last}
            aria-label={`${prefix}${t(`mappings.editor.move.down.${noun}`, { n })}`}
            onClick={() => onMove(1)}
          >
            <ArrowDown aria-hidden className="size-4" />
          </Button>
        </>
      )}
      <Button
        type="button"
        variant="ghost"
        size="icon"
        aria-label={`${prefix}${t(`mappings.editor.move.remove.${noun}`, { n })}`}
        onClick={onRemove}
      >
        <Trash2 aria-hidden className="size-4" />
      </Button>
    </div>
  );
}

/** Editor of one expression tree node: direct, constant, concat or transform. */
export function ExprEditor({
  value,
  onChange,
  prefix,
  sourceListId,
}: { value: FExpr; onChange: (value: FExpr) => void } & Shared) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3">
      <SelectField
        label={`${prefix}${t("mappings.editor.expr.kind")}`}
        value={value.type}
        onChange={(kind) => onChange(changeExprKind(value, kind as ExprKind))}
      >
        {EXPR_KINDS.map((kind) => (
          <option key={kind} value={kind}>
            {t(`mappings.editor.expr.kinds.${kind}`)}
          </option>
        ))}
      </SelectField>
      <ExprBody value={value} onChange={onChange} prefix={prefix} sourceListId={sourceListId} />
    </div>
  );
}

function ExprBody({
  value,
  onChange,
  prefix,
  sourceListId,
}: { value: FExpr; onChange: (value: FExpr) => void } & Shared) {
  const { t } = useTranslation();
  switch (value.type) {
    case "direct":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={`${prefix}${t("mappings.editor.expr.source")}`}
            value={value.source}
            list={sourceListId}
            mono
            hint={t("mappings.editor.expr.sourceHint")}
            onChange={(source) => onChange({ ...value, source })}
          />
          <TextField
            label={`${prefix}${t("mappings.editor.expr.default")}`}
            value={value.default}
            hint={t("mappings.editor.expr.defaultHint")}
            onChange={(next) => onChange({ ...value, default: next })}
          />
        </div>
      );
    case "constant":
      return (
        <TextField
          label={`${prefix}${t("mappings.editor.expr.value")}`}
          value={value.value}
          hint={t("mappings.editor.expr.valueHint")}
          onChange={(next) => onChange({ ...value, value: next })}
        />
      );
    case "concat":
      return (
        <div className="flex flex-col gap-3">
          <div className="grid items-end gap-3 sm:grid-cols-2">
            <TextField
              label={`${prefix}${t("mappings.editor.expr.separator")}`}
              value={value.separator}
              onChange={(separator) => onChange({ ...value, separator })}
            />
            <CheckField
              label={`${prefix}${t("mappings.editor.expr.skipEmpty")}`}
              checked={value.skipEmpty}
              onChange={(skipEmpty) => onChange({ ...value, skipEmpty })}
            />
          </div>
          <ExprList
            items={value.parts}
            noun="part"
            prefix={prefix}
            sourceListId={sourceListId}
            onChange={(parts) => onChange({ ...value, parts })}
          />
        </div>
      );
    case "transform":
      return (
        <div className="flex flex-col gap-3">
          <div className="rounded-md border border-dashed p-3">
            <ExprEditor
              value={value.input}
              prefix={`${prefix}${t("mappings.editor.expr.inputPrefix")} · `}
              sourceListId={sourceListId}
              onChange={(input) => onChange({ ...value, input })}
            />
          </div>
          <StepList
            steps={value.steps}
            prefix={prefix}
            sourceListId={sourceListId}
            onChange={(steps) => onChange({ ...value, steps })}
          />
        </div>
      );
  }
}

/** Ordered sub-expressions (concat parts, coalesce alternatives) with add / move / remove. */
function ExprList({
  items,
  noun,
  prefix,
  sourceListId,
  onChange,
}: {
  items: FExpr[];
  noun: "part" | "alternative";
  onChange: (items: FExpr[]) => void;
} & Shared) {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col gap-3">
      {items.length > 0 && (
        <ol className="flex flex-col gap-3">
          {items.map((item, index) => {
            const itemPrefix = `${prefix}${t(`mappings.editor.expr.${noun}Prefix`, { n: index + 1 })} · `;
            return (
              <li key={index} className="flex flex-col gap-2 rounded-md border p-3">
                <div className="flex items-start justify-between gap-2">
                  <span className="text-sm font-medium">
                    {t(`mappings.editor.expr.${noun}Prefix`, { n: index + 1 })}
                  </span>
                  <ListButtons
                    prefix={prefix}
                    noun={noun}
                    n={index + 1}
                    first={index === 0}
                    last={index === items.length - 1}
                    onMove={(delta) => onChange(moveItem(items, index, delta))}
                    onRemove={() => onChange(removeAt(items, index))}
                  />
                </div>
                <ExprEditor
                  value={item}
                  prefix={itemPrefix}
                  sourceListId={sourceListId}
                  onChange={(next) => onChange(replaceAt(items, index, next))}
                />
              </li>
            );
          })}
        </ol>
      )}
      <div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => onChange([...items, defaultExpr("direct")])}
        >
          <Plus aria-hidden className="size-4" />
          {`${prefix}${t(`mappings.editor.expr.add.${noun}`)}`}
        </Button>
      </div>
    </div>
  );
}

function StepList({
  steps,
  prefix,
  sourceListId,
  onChange,
}: { steps: FStep[]; onChange: (steps: FStep[]) => void } & Shared) {
  const { t } = useTranslation();
  const [next, setNext] = useState<StepType>("trim");
  return (
    <div className="flex flex-col gap-3">
      <h4 className="text-sm font-medium">{`${prefix}${t("mappings.editor.steps.title")}`}</h4>
      {steps.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t("mappings.editor.steps.none")}</p>
      ) : (
        <ol className="flex flex-col gap-3">
          {steps.map((step, index) => (
            <li key={index} className="flex flex-col gap-2 rounded-md border p-3">
              <div className="flex items-start justify-between gap-2">
                <span className="text-sm font-medium">
                  {t("mappings.editor.steps.label", {
                    n: index + 1,
                    name: t(`mappings.editor.steps.names.${step.type}`),
                  })}
                </span>
                <ListButtons
                  prefix={prefix}
                  noun="step"
                  n={index + 1}
                  first={index === 0}
                  last={index === steps.length - 1}
                  onMove={(delta) => onChange(moveItem(steps, index, delta))}
                  onRemove={() => onChange(removeAt(steps, index))}
                />
              </div>
              <StepParams
                step={step}
                prefix={prefix}
                sourceListId={sourceListId}
                onChange={(updated) => onChange(replaceAt(steps, index, updated))}
              />
            </li>
          ))}
        </ol>
      )}
      <div className="flex flex-wrap items-end gap-2">
        <div className="w-60">
          <SelectField
            label={`${prefix}${t("mappings.editor.steps.type")}`}
            value={next}
            onChange={(type) => setNext(type as StepType)}
          >
            {STEP_TYPES.map((type) => (
              <option key={type} value={type}>
                {t(`mappings.editor.steps.names.${type}`)}
              </option>
            ))}
          </SelectField>
        </div>
        <Button
          type="button"
          variant="outline"
          onClick={() => onChange([...steps, defaultStep(next)])}
        >
          <Plus aria-hidden className="size-4" />
          {`${prefix}${t("mappings.editor.steps.add")}`}
        </Button>
      </div>
    </div>
  );
}

function StepParams({
  step,
  onChange,
  prefix,
  sourceListId,
}: { step: FStep; onChange: (step: FStep) => void } & Shared) {
  const { t } = useTranslation();
  const label = (key: string) => `${prefix}${t(`mappings.editor.steps.params.${key}`)}`;
  switch (step.type) {
    case "replace":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={label("old")}
            value={step.old}
            onChange={(old) => onChange({ ...step, old })}
          />
          <TextField
            label={label("new")}
            value={step.new}
            onChange={(value) => onChange({ ...step, new: value })}
          />
        </div>
      );
    case "default":
      return (
        <TextField
          label={label("value")}
          value={step.value}
          hint={t("mappings.editor.expr.valueHint")}
          onChange={(value) => onChange({ ...step, value })}
        />
      );
    case "date_format":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={label("inFormat")}
            value={step.inFormat}
            mono
            hint={t("mappings.editor.steps.params.formatHint")}
            onChange={(inFormat) => onChange({ ...step, inFormat })}
          />
          <TextField
            label={label("outFormat")}
            value={step.outFormat}
            mono
            hint={t("mappings.editor.steps.params.formatHint")}
            onChange={(outFormat) => onChange({ ...step, outFormat })}
          />
        </div>
      );
    case "to_cents":
      return (
        <TextField
          label={label("factor")}
          value={step.factor}
          hint={t("mappings.editor.steps.params.factorHint")}
          onChange={(factor) => onChange({ ...step, factor })}
        />
      );
    case "from_cents":
      return (
        <div className="grid items-end gap-3 sm:grid-cols-2">
          <TextField
            label={label("factor")}
            value={step.factor}
            hint={t("mappings.editor.steps.params.factorHint")}
            onChange={(factor) => onChange({ ...step, factor })}
          />
          <CheckField
            label={label("asString")}
            checked={step.asString}
            onChange={(asString) => onChange({ ...step, asString })}
          />
        </div>
      );
    case "substring":
      return (
        <div className="grid gap-3 sm:grid-cols-2">
          <TextField
            label={label("start")}
            value={step.start}
            onChange={(start) => onChange({ ...step, start })}
          />
          <TextField
            label={label("end")}
            value={step.end}
            onChange={(end) => onChange({ ...step, end })}
          />
        </div>
      );
    case "coalesce":
      return (
        <ExprList
          items={step.alternatives}
          noun="alternative"
          prefix={prefix}
          sourceListId={sourceListId}
          onChange={(alternatives) => onChange({ ...step, alternatives })}
        />
      );
    case "lookup":
      return <LookupParams step={step} prefix={prefix} onChange={onChange} />;
    default:
      return null;
  }
}

const POLICIES: readonly LookupMissing[] = ["error", "passthrough", "default"];

function LookupParams({
  step,
  prefix,
  onChange,
}: {
  step: Extract<FStep, { type: "lookup" }>;
  prefix: string;
  onChange: (step: FStep) => void;
}) {
  const { t } = useTranslation();
  const label = (key: string, params?: Record<string, unknown>) =>
    `${prefix}${t(`mappings.editor.steps.params.${key}`, params)}`;
  return (
    <div className="flex flex-col gap-3">
      <SelectField
        label={label("onMissing")}
        value={step.onMissing}
        onChange={(onMissing) => onChange({ ...step, onMissing: onMissing as LookupMissing })}
      >
        {POLICIES.map((policy) => (
          <option key={policy} value={policy}>
            {t(`mappings.editor.steps.params.policies.${policy}`)}
          </option>
        ))}
      </SelectField>
      {step.onMissing === "default" && (
        <TextField
          label={label("lookupDefault")}
          value={step.default}
          hint={t("mappings.editor.expr.valueHint")}
          onChange={(value) => onChange({ ...step, default: value })}
        />
      )}
      <div className="flex flex-col gap-2">
        {step.rows.map((row, index) => (
          <div key={index} className="flex items-end gap-2">
            <div className="grid flex-1 gap-2 sm:grid-cols-2">
              <TextField
                label={label("rowFrom", { n: index + 1 })}
                value={row.from}
                onChange={(from) =>
                  onChange({ ...step, rows: replaceAt(step.rows, index, { ...row, from }) })
                }
              />
              <TextField
                label={label("rowTo", { n: index + 1 })}
                value={row.to}
                onChange={(to) =>
                  onChange({ ...step, rows: replaceAt(step.rows, index, { ...row, to }) })
                }
              />
            </div>
            <ListButtons
              prefix={prefix}
              noun="row"
              n={index + 1}
              first
              last
              onMove={() => undefined}
              onRemove={() => onChange({ ...step, rows: removeAt(step.rows, index) })}
            />
          </div>
        ))}
        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => onChange({ ...step, rows: [...step.rows, { from: "", to: "" }] })}
          >
            <Plus aria-hidden className="size-4" />
            {label("addRow")}
          </Button>
        </div>
      </div>
    </div>
  );
}
