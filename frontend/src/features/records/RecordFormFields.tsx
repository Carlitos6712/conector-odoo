import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import { FormField } from "@/features/connections/FormField";
import type { FormValues } from "@/features/records/columns";
import type { FieldSpec } from "@/features/records/types";

const NUMBER_TYPES = new Set(["integer", "float", "monetary", "number"]);

/** The inputs shared by the create and edit dialogs: one control per field spec. */
export function RecordFormFields({
  specs,
  form,
  fieldErrors,
  onChange,
}: {
  specs: readonly FieldSpec[];
  form: FormValues;
  fieldErrors: Record<string, string>;
  onChange: (name: string, value: string | boolean) => void;
}) {
  return (
    <div className="flex max-h-[60vh] flex-col gap-4 overflow-y-auto pr-1">
      {specs.map((spec) => {
        const value = form[spec.name] ?? "";
        return (
          <FormField
            key={spec.name}
            name={spec.name}
            label={spec.label ?? spec.name}
            required={spec.required}
            error={fieldErrors[spec.name]}
          >
            {(control) =>
              spec.type === "boolean" ? (
                <input
                  {...control}
                  type="checkbox"
                  className="size-4"
                  checked={value === true}
                  onChange={(e) => onChange(spec.name, e.target.checked)}
                />
              ) : spec.choices && spec.choices.length > 0 ? (
                <Select
                  {...control}
                  value={String(value)}
                  onChange={(e) => onChange(spec.name, e.target.value)}
                >
                  <option value="" />
                  {spec.choices.map((choice) => (
                    <option key={choice} value={choice}>
                      {choice}
                    </option>
                  ))}
                </Select>
              ) : (
                <Input
                  {...control}
                  type={NUMBER_TYPES.has(spec.type) ? "number" : "text"}
                  step={spec.type === "integer" ? 1 : "any"}
                  value={String(value)}
                  onChange={(e) => onChange(spec.name, e.target.value)}
                />
              )
            }
          </FormField>
        );
      })}
    </div>
  );
}
