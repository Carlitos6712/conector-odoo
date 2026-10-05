import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { CheckboxGroup } from "@/components/ui/checkbox-group";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { RadioGroup } from "@/components/ui/radio-group";
import { buildCron, detectPreset, nextFires, validateCron } from "@/features/jobs/cron";
import { cronSentence } from "@/features/jobs/cronText";

type Mode = "hourly" | "daily" | "weekly" | "advanced";
const MODES: readonly Mode[] = ["hourly", "daily", "weekly", "advanced"];
/** Monday first, as people read a week. */
const WEEK_ORDER = ["1", "2", "3", "4", "5", "6", "0"] as const;

const utcStamp = (date: Date) => {
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 16)} UTC`;
};

/**
 * Schedule editor: presets (hourly, daily, weekly) or an advanced 5-field expression. It always
 * shows what the expression means and when it will fire next (UTC, like the backend scheduler).
 */
export function CronEditor({
  value,
  onChange,
  error,
}: {
  value: string;
  onChange: (cron: string) => void;
  /** Already translated; shown when the expression itself has no problem to report. */
  error?: string;
}) {
  const { t } = useTranslation();
  const [initial] = useState(() => detectPreset(value));
  const [mode, setMode] = useState<Mode>(initial?.kind ?? "advanced");
  const [minute, setMinute] = useState(String(initial?.minute ?? 0));
  const [hour, setHour] = useState(String(initial && initial.kind !== "hourly" ? initial.hour : 2));
  const [days, setDays] = useState<string[]>(
    initial?.kind === "weekly" ? initial.days.map(String) : ["1"],
  );

  const apply = (next: { mode?: Mode; minute?: string; hour?: string; days?: string[] }) => {
    const m = next.mode ?? mode;
    const nextMinute = next.minute ?? minute;
    const nextHour = next.hour ?? hour;
    const nextDays = next.days ?? days;
    if (next.mode !== undefined) setMode(m);
    if (next.minute !== undefined) setMinute(nextMinute);
    if (next.hour !== undefined) setHour(nextHour);
    if (next.days !== undefined) setDays(nextDays);
    if (m === "advanced") return;
    const spec = { minute: Number(nextMinute || NaN), hour: Number(nextHour || NaN) };
    const cron =
      m === "hourly"
        ? buildCron({ kind: "hourly", minute: spec.minute })
        : m === "daily"
          ? buildCron({ kind: "daily", ...spec })
          : buildCron({ kind: "weekly", ...spec, days: nextDays.map(Number) });
    if (cron !== null) onChange(cron);
  };

  const issue = validateCron(value);
  const valid = issue === null;
  const fires = useMemo(() => (valid ? nextFires(value, new Date(), 3) : []), [value, valid]);
  const message = issue
    ? t(`jobs.cron.errors.${issue.code}`)
    : fires.length === 0
      ? t("jobs.cron.neverFires")
      : error;
  const sentence = issue === null ? cronSentence(t, value) : null;

  return (
    <div className="flex flex-col gap-4">
      <RadioGroup
        legend={t("jobs.cron.editor.frequency")}
        name="cron-mode"
        value={mode}
        options={MODES.map((m) => ({ value: m, label: t(`jobs.cron.editor.presets.${m}`) }))}
        onChange={(m) => apply({ mode: m as Mode })}
      />

      {mode !== "advanced" && (
        <div className="flex flex-wrap items-end gap-4">
          {mode !== "hourly" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="cron-hour">{t("jobs.cron.editor.hour")}</Label>
              <Input
                id="cron-hour"
                type="number"
                min={0}
                max={23}
                className="w-24"
                value={hour}
                onChange={(event) => apply({ hour: event.target.value })}
              />
            </div>
          )}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="cron-minute">{t("jobs.cron.editor.minute")}</Label>
            <Input
              id="cron-minute"
              type="number"
              min={0}
              max={59}
              className="w-24"
              value={minute}
              onChange={(event) => apply({ minute: event.target.value })}
            />
          </div>
        </div>
      )}

      {mode === "weekly" && (
        <CheckboxGroup
          inline
          legend={t("jobs.cron.editor.days")}
          values={days}
          options={WEEK_ORDER.map((day) => ({
            value: day,
            label: t(`jobs.cron.weekdaysShort.${day}`),
          }))}
          onChange={(next) => apply({ days: next })}
        />
      )}

      {mode === "advanced" && (
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cron-expression">{t("jobs.cron.editor.expression")}</Label>
          <Input
            id="cron-expression"
            className="font-mono"
            value={value}
            aria-invalid={issue || fires.length === 0 ? "true" : undefined}
            aria-describedby="cron-expression-hint"
            onChange={(event) => onChange(event.target.value)}
          />
          <p id="cron-expression-hint" className="text-xs text-muted-foreground">
            {t("jobs.cron.editor.expressionHint")}
          </p>
        </div>
      )}

      {message && (
        <p role="alert" className="text-sm text-destructive">
          {message}
        </p>
      )}
      {sentence && <p className="text-sm font-medium">{sentence}</p>}
      {fires.length > 0 && (
        <div className="flex flex-col gap-1 text-sm">
          <p id="cron-fires-label" className="text-muted-foreground">
            {t("jobs.cron.editor.nextFires")}
          </p>
          <ul aria-labelledby="cron-fires-label" className="font-mono text-xs">
            {fires.map((fire) => (
              <li key={fire.toISOString()}>{utcStamp(fire)}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
