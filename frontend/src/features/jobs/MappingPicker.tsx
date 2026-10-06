import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Select } from "@/components/ui/select";
import { FormField } from "@/features/connections/FormField";
import { useMappingVersions } from "@/features/mappings/hooks";
import type { StoredMapping } from "@/features/mappings/types";

function VersionSelect({
  id,
  label,
  name,
  version,
  onVersion,
}: {
  id: string;
  label: string;
  name: string;
  version: string;
  onVersion: (version: string) => void;
}) {
  const { t } = useTranslation();
  const versions = useMappingVersions(name);
  const numbers = (versions.data ?? []).map((item) => String(item.version));
  const options = version !== "" && !numbers.includes(version) ? [version, ...numbers] : numbers;
  return (
    <FormField name={id} label={label} required={false}>
      {(props) => (
        <Select {...props} value={version} onChange={(event) => onVersion(event.target.value)}>
          <option value="">{t("jobs.wizard.endpoints.latest")}</option>
          {options.map((number) => (
            <option key={number} value={number}>
              v{number}
            </option>
          ))}
        </Select>
      )}
    </FormField>
  );
}

/**
 * Picks a saved mapping (and optionally pins a version). Only mappings that fit the chosen
 * resources are offered; a selection that no longer fits stays visible, marked, so it can be
 * replaced knowingly.
 */
export function MappingPicker({
  id,
  label,
  versionLabel,
  hint,
  compatible,
  name,
  version,
  error,
  noneFits,
  onName,
  onVersion,
}: {
  id: string;
  label: string;
  versionLabel: string;
  hint: string;
  compatible: readonly StoredMapping[];
  name: string;
  version: string;
  error?: string;
  /** Set when both resources are chosen but no saved mapping connects them. */
  noneFits?: { source: string; target: string };
  onName: (name: string) => void;
  onVersion: (version: string) => void;
}) {
  const { t } = useTranslation();
  const names = compatible.map((mapping) => mapping.name);
  const stale = name !== "" && !names.includes(name);
  return (
    <div className="flex flex-col gap-3">
      <FormField name={id} label={label} error={error} hint={hint}>
        {(props) => (
          <Select {...props} value={name} onChange={(event) => onName(event.target.value)}>
            <option value="">{t("jobs.wizard.endpoints.pick")}</option>
            {stale && (
              <option value={name}>{t("jobs.wizard.endpoints.incompatible", { name })}</option>
            )}
            {names.map((candidate) => (
              <option key={candidate} value={candidate}>
                {candidate}
              </option>
            ))}
          </Select>
        )}
      </FormField>
      {noneFits && names.length === 0 && (
        <p className="text-sm text-muted-foreground">
          {t("jobs.wizard.endpoints.noneFits", noneFits)}{" "}
          <Link to="/mappings/new" className="font-medium underline underline-offset-2">
            {t("jobs.wizard.endpoints.createMapping")}
          </Link>
        </p>
      )}
      {name !== "" && (
        <VersionSelect
          id={`${id}Version`}
          label={versionLabel}
          name={name}
          version={version}
          onVersion={onVersion}
        />
      )}
    </div>
  );
}
