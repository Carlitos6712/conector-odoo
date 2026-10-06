import { useId, type ReactNode } from "react";
import { Label } from "@/components/ui/label";

/** Label + control + optional hint and error, wired with `aria-describedby`/`aria-invalid`. */
export function Field({
  label,
  hint,
  error,
  children,
}: {
  label: string;
  hint?: string;
  error?: string | null;
  children: (props: {
    id: string;
    "aria-invalid": boolean;
    "aria-describedby": string | undefined;
  }) => ReactNode;
}) {
  const id = useId();
  const describedBy =
    [hint ? `${id}-hint` : null, error ? `${id}-error` : null].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div className="flex flex-col gap-2">
      <Label htmlFor={id}>{label}</Label>
      {children({ id, "aria-invalid": Boolean(error), "aria-describedby": describedBy })}
      {hint && (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      )}
      {error && (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}

/** Minimum length enforced by the backend password policy (`domain/auth.py`). */
export const MIN_PASSWORD_LENGTH = 12;
