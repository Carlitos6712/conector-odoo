import type { ReactNode } from "react";
import { Label } from "@/components/ui/label";

export interface ControlProps {
  id: string;
  "aria-describedby"?: string;
  "aria-invalid"?: "true";
  "aria-required"?: true;
}

/** Label + control + inline error/hint, wired through `aria-describedby` and `aria-invalid`. */
export function FormField({
  name,
  label,
  error,
  hint,
  required = true,
  children,
}: {
  name: string;
  label: string;
  error?: string;
  hint?: string;
  required?: boolean;
  children: (props: ControlProps) => ReactNode;
}) {
  const id = `field-${name}`;
  const describedBy = error ? `${id}-error` : hint ? `${id}-hint` : undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children({
        id,
        "aria-describedby": describedBy,
        "aria-invalid": error ? "true" : undefined,
        "aria-required": required ? true : undefined,
      })}
      {error ? (
        <p id={`${id}-error`} className="text-sm text-destructive">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-hint`} className="text-sm text-muted-foreground">
          {hint}
        </p>
      ) : null}
    </div>
  );
}
