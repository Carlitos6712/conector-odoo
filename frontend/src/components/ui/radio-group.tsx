import { useId } from "react";
import { cn } from "@/lib/utils";

export interface ChoiceOption {
  value: string;
  label: string;
  description?: string;
}

/**
 * Single choice among a few options, shown as cards. Native radios sharing a `name`, so arrow
 * keys, focus and screen-reader semantics come from the browser.
 */
export function RadioGroup({
  legend,
  name,
  value,
  options,
  onChange,
  disabled,
  error,
}: {
  legend: string;
  name: string;
  value: string;
  options: readonly ChoiceOption[];
  onChange: (value: string) => void;
  disabled?: boolean;
  error?: string;
}) {
  const base = useId();
  return (
    <fieldset
      className="flex flex-col gap-2"
      aria-describedby={error ? `${base}-error` : undefined}
    >
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {options.map((option) => {
        const id = `${base}-${option.value}`;
        return (
          <div
            key={option.value}
            className={cn(
              "flex items-start gap-3 rounded-md border p-3",
              value === option.value && "border-primary",
            )}
          >
            <input
              type="radio"
              id={id}
              name={name}
              className="mt-1 accent-primary"
              checked={value === option.value}
              disabled={disabled}
              aria-describedby={option.description ? `${id}-desc` : undefined}
              onChange={() => onChange(option.value)}
            />
            <div className="flex flex-col">
              <label htmlFor={id} className="font-medium">
                {option.label}
              </label>
              {option.description && (
                <span id={`${id}-desc`} className="text-sm text-muted-foreground">
                  {option.description}
                </span>
              )}
            </div>
          </div>
        );
      })}
      {error && (
        <p id={`${base}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </fieldset>
  );
}
