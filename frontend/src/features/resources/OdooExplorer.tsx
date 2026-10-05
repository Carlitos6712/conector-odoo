import { useState } from "react";
import { useTranslation } from "react-i18next";
import { useSession } from "@/auth/useSession";
import { EmptyState } from "@/components/EmptyState";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { describeResourceError } from "@/features/resources/errors";
import { useDiscoverModels, usePreview } from "@/features/resources/hooks";
import { SchemaTable } from "@/features/resources/PreviewPanel";
import { cn } from "@/lib/utils";

const MAX_LISTED = 200;

function ErrorBlock({ error, onRetry }: { error: unknown; onRetry: () => void }) {
  const { t } = useTranslation();
  const described = describeResourceError(error, "discover");
  return (
    <div role="alert" className="flex flex-col items-start gap-2 text-sm">
      <p className="text-destructive">{t(described.messageKey, described.params)}</p>
      {described.detail && <p className="break-words text-muted-foreground">{described.detail}</p>}
      <Button variant="outline" size="sm" onClick={onRetry}>
        {t("common.retry")}
      </Button>
    </div>
  );
}

/** Read-only view of the chosen model: only its fields, never its data. */
function ModelFields({ profileId, model }: { profileId: number; model: string }) {
  const { t } = useTranslation();
  // The API returns the schema together with a sample; one record is the smallest request.
  const preview = usePreview(profileId, model, 1);
  if (preview.isPending) return <Loading />;
  if (preview.isError) {
    return <ErrorBlock error={preview.error} onRetry={() => void preview.refetch()} />;
  }
  const { fields } = preview.data.schema;
  return fields.length === 0 ? (
    <p className="text-sm text-muted-foreground">{t("resources.odoo.noFields")}</p>
  ) : (
    <SchemaTable fields={fields} label={t("resources.odoo.fieldsOf", { model })} />
  );
}

/** Odoo models are discovered (ir.model) and addressed by name; they are not catalog entries. */
export function OdooExplorer({ profileId }: { profileId: number }) {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const models = useDiscoverModels(profileId, canMutate);
  const [search, setSearch] = useState("");
  const [selected, setSelected] = useState<string | null>(null);

  if (!canMutate) return <EmptyState message={t("resources.odoo.adminOnly")} />;
  if (models.isPending) return <Loading />;
  if (models.isError) {
    return <ErrorBlock error={models.error} onRetry={() => void models.refetch()} />;
  }

  const needle = search.trim().toLowerCase();
  const matches = models.data.filter(
    (m) =>
      !needle || m.name.toLowerCase().includes(needle) || m.label.toLowerCase().includes(needle),
  );
  const listed = matches.slice(0, MAX_LISTED);

  return (
    <div className="flex flex-col gap-4">
      <p className="text-sm text-muted-foreground">{t("resources.odoo.intro")}</p>
      <div className="grid gap-6 lg:grid-cols-[minmax(0,20rem)_1fr]">
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="odoo-model-search">{t("resources.odoo.search")}</Label>
            <Input
              id="odoo-model-search"
              type="search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </div>
          {listed.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("resources.odoo.noMatches")}</p>
          ) : (
            <ul className="flex max-h-96 flex-col overflow-y-auto rounded-md border">
              {listed.map((model) => (
                <li key={model.name}>
                  <button
                    type="button"
                    aria-pressed={selected === model.name}
                    onClick={() => setSelected(model.name)}
                    className={cn(
                      "flex w-full flex-col items-start px-3 py-2 text-left text-sm hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring",
                      selected === model.name && "bg-accent",
                    )}
                  >
                    <span className="font-mono text-xs font-medium">{model.name}</span>
                    {model.label !== model.name && (
                      <span className="text-muted-foreground">{model.label}</span>
                    )}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {matches.length > listed.length && (
            <p className="text-xs text-muted-foreground">
              {t("resources.odoo.truncated", { shown: listed.length, total: matches.length })}
            </p>
          )}
        </div>
        <div>
          {selected ? (
            <div className="flex flex-col gap-3">
              <h2 className="text-lg font-semibold">
                {t("resources.odoo.fieldsTitle", { model: selected })}
              </h2>
              <ModelFields key={selected} profileId={profileId} model={selected} />
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">{t("resources.odoo.pick")}</p>
          )}
        </div>
      </div>
    </div>
  );
}
