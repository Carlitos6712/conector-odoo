import { useId } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import type { ChoiceOption } from "@/components/ui/radio-group";
import { cn } from "@/lib/utils";

/**
 * Multi-select as a group of checkboxes. The selection always comes back in the order of the
 * options, so the stored value does not depend on the order in which the user ticked them.
 */
export function CheckboxGroup({
  legend,
  values,
  options,
  onChange,
  error,
  inline,
}: {
  legend: string;
  values: readonly string[];
  options: readonly ChoiceOption[];
  onChange: (values: string[]) => void;
  error?: string;
  /** Lay the options out in a row (short labels such as weekdays). */
  inline?: boolean;
}) {
  const base = useId();
  const toggle = (value: string, on: boolean) =>
    onChange(
      options
        .map((option) => option.value)
        .filter((candidate) => (candidate === value ? on : values.includes(candidate))),
    );
  return (
    <fieldset
      className="flex flex-col gap-2"
      aria-describedby={error ? `${base}-error` : undefined}
    >
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      <div className={cn("flex gap-3", inline ? "flex-wrap" : "flex-col")}>
        {options.map((option) => {
          const id = `${base}-${option.value}`;
          return (
            <div key={option.value} className="flex items-start gap-2">
              <Checkbox
                id={id}
                className="mt-0.5"
                checked={values.includes(option.value)}
                aria-describedby={option.description ? `${id}-desc` : undefined}
                onChange={(event) => toggle(option.value, event.target.checked)}
              />
              <div className="flex flex-col">
                <label htmlFor={id} className="text-sm">
                  {option.label}
                </label>
                {option.description && (
                  <span id={`${id}-desc`} className="text-xs text-muted-foreground">
                    {option.description}
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      {error && (
        <p id={`${base}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}
