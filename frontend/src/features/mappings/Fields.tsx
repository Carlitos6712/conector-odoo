import { useId, type ReactNode } from "react";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";

/** Small labelled controls shared by the mapping editor (label wired by `htmlFor`). */
export function TextField({
  label,
  value,
  onChange,
  hint,
  list,
  mono,
  readOnly,
  onCommit,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  hint?: string;
  list?: string;
  mono?: boolean;
  readOnly?: boolean;
  /** Called when the input loses focus or Enter is pressed. */
  onCommit?: () => void;
}) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        list={list}
        value={value}
        readOnly={readOnly}
        className={mono ? "font-mono text-xs" : undefined}
        aria-describedby={hint ? `${id}-hint` : undefined}
        onChange={(event) => onChange(event.target.value)}
        onBlur={onCommit}
        onKeyDown={onCommit && ((event) => event.key === "Enter" && onCommit())}
      />
      {hint && (
        <p id={`${id}-hint`} className="text-xs text-muted-foreground">
          {hint}
        </p>
      )}
    </div>
  );
}

export function SelectField({
  label,
  value,
  onChange,
  children,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  children: ReactNode;
}) {
  const id = useId();
  return (
    <div className="flex min-w-0 flex-col gap-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Select id={id} value={value} onChange={(event) => onChange(event.target.value)}>
        {children}
      </Select>
    </div>
  );
}

export function CheckField({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  return (
    <div className="flex items-center gap-2">
      <Checkbox id={id} checked={checked} onChange={(event) => onChange(event.target.checked)} />
      <Label htmlFor={id}>{label}</Label>
    </div>
  );
}
