import { Eye, Pencil, Plus, Trash2, Upload } from "lucide-react";
import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useSearchParams } from "react-router-dom";
import { AdminOnly } from "@/auth/AdminOnly";
import { useSession } from "@/auth/useSession";
import { EmptyState } from "@/components/EmptyState";
import { ErrorState } from "@/components/ErrorState";
import { Loading } from "@/components/Loading";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select } from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useProfiles } from "@/features/connections/hooks";
import type { Profile } from "@/features/connections/types";
import { DeleteResourceDialog, type ResourceRef } from "@/features/resources/DeleteResourceDialog";
import { useAllResources } from "@/features/resources/hooks";
import { PreviewPanel } from "@/features/resources/PreviewPanel";
import type { StoredResource } from "@/features/resources/types";

const ALL = "all";

interface Row {
  profile: Profile;
  stored: StoredResource;
}

function endpointLabel(stored: StoredResource): string {
  const spec = stored.config.list_endpoint ?? stored.config.get_endpoint;
  return spec ? `${spec.method} ${spec.path}` : "—";
}

export function ResourcesPage() {
  const { t } = useTranslation();
  const { canMutate } = useSession();
  const profiles = useProfiles();
  const [params, setParams] = useSearchParams();
  const [previewing, setPreviewing] = useState<ResourceRef | null>(null);
  const [toDelete, setToDelete] = useState<ResourceRef | null>(null);

  const restProfiles = (profiles.data ?? []).filter((p) => p.type === "rest");
  const requested = params.get("profile") ?? ALL;
  const selected = restProfiles.find((p) => String(p.id) === requested) ?? null;
  const scope = selected ? [selected] : restProfiles;
  const listings = useAllResources(scope.map((p) => p.id));

  const newTo = selected ? `/resources/new?profile=${selected.id}` : "/resources/new";
  const importTo = selected ? `/resources/import?profile=${selected.id}` : "/resources/import";
  const actions = (
    <AdminOnly>
      <div className="flex flex-wrap gap-2">
        <Button variant="outline" asChild>
          <Link to={importTo}>
            <Upload aria-hidden className="size-4" />
            {t("resources.import")}
          </Link>
        </Button>
        <Button asChild>
          <Link to={newTo}>
            <Plus aria-hidden className="size-4" />
            {t("resources.new")}
          </Link>
        </Button>
      </div>
    </AdminOnly>
  );

  let body;
  if (profiles.isPending) body = <Loading />;
  else if (profiles.isError)
    body = <ErrorState error={profiles.error} onRetry={() => void profiles.refetch()} />;
  else if (restProfiles.length === 0)
    body = (
      <EmptyState
        message={t(canMutate ? "resources.noProfiles" : "resources.noProfilesReadOnly")}
        action={
          <AdminOnly>
            <Button asChild>
              <Link to="/connections/new">{t("connections.new")}</Link>
            </Button>
          </AdminOnly>
        }
      />
    );
  else if (listings.some((q) => q.isPending)) body = <Loading />;
  else if (listings.some((q) => q.isError)) {
    const failed = listings.find((q) => q.isError);
    body = (
      <ErrorState error={failed?.error} onRetry={() => listings.forEach((q) => void q.refetch())} />
    );
  } else {
    const rows: Row[] = scope.flatMap((profile, index) =>
      (listings[index]?.data?.items ?? []).map((stored) => ({ profile, stored })),
    );
    const invalid = scope.flatMap((profile, index) =>
      (listings[index]?.data?.invalid ?? []).map((problem) => ({ profile, problem })),
    );
    body = (
      <>
        {invalid.length > 0 && (
          <div role="alert" className="rounded-md border border-destructive p-3 text-sm">
            <p className="font-medium text-destructive">
              {t("resources.invalid.title", { count: invalid.length })}
            </p>
            <ul className="mt-1 list-disc pl-5">
              {invalid.map(({ profile, problem }) => (
                <li key={`${profile.id}/${problem.name}`}>
                  <span className="font-mono">{problem.name}</span> ({profile.name})
                </li>
              ))}
            </ul>
          </div>
        )}
        {rows.length === 0 ? (
          <EmptyState
            message={t(canMutate ? "resources.empty" : "resources.emptyReadOnly")}
            action={actions}
          />
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t("resources.columns.connection")}</TableHead>
                <TableHead>{t("resources.columns.name")}</TableHead>
                <TableHead>{t("resources.columns.endpoint")}</TableHead>
                <TableHead>{t("resources.columns.pagination")}</TableHead>
                <TableHead>{t("resources.columns.source")}</TableHead>
                <AdminOnly>
                  <TableHead>
                    <span className="sr-only">{t("resources.columns.actions")}</span>
                  </TableHead>
                </AdminOnly>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map(({ profile, stored }) => {
                const ref = { profileId: profile.id, name: stored.config.name };
                const none = stored.config.pagination.strategy === "none";
                return (
                  <TableRow key={`${profile.id}/${stored.config.name}`}>
                    <TableCell>{profile.name}</TableCell>
                    <TableCell>
                      <div className="font-mono text-xs font-medium">{stored.config.name}</div>
                      {stored.config.label && stored.config.label !== stored.config.name && (
                        <div className="text-muted-foreground">{stored.config.label}</div>
                      )}
                    </TableCell>
                    <TableCell className="break-all font-mono text-xs">
                      {endpointLabel(stored)}
                    </TableCell>
                    <TableCell>
                      <Badge variant={none ? "outline" : "secondary"}>
                        {t(`resources.pagination.${stored.config.pagination.strategy}`)}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge variant="outline">{t(`resources.sources.${stored.source}`)}</Badge>
                    </TableCell>
                    <AdminOnly>
                      <TableCell>
                        <div className="flex justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("resources.actions.preview", { name: ref.name })}
                            onClick={() => setPreviewing(ref)}
                          >
                            <Eye aria-hidden className="size-4" />
                          </Button>
                          <Button variant="ghost" size="icon" asChild>
                            <Link
                              to={`/resources/${profile.id}/${encodeURIComponent(ref.name)}/edit`}
                              aria-label={t("resources.actions.edit", { name: ref.name })}
                            >
                              <Pencil aria-hidden className="size-4" />
                            </Link>
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            aria-label={t("resources.actions.delete", { name: ref.name })}
                            onClick={() => setToDelete(ref)}
                          >
                            <Trash2 aria-hidden className="size-4" />
                          </Button>
                        </div>
                      </TableCell>
                    </AdminOnly>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </>
    );
  }

  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">{t("nav.resources")}</h1>
        {restProfiles.length > 0 && actions}
      </div>
      {restProfiles.length > 0 && (
        <div className="flex max-w-xs flex-col gap-1.5">
          <Label htmlFor="resources-profile">{t("resources.filter.label")}</Label>
          <Select
            id="resources-profile"
            value={selected ? String(selected.id) : ALL}
            onChange={(event) => {
              const value = event.target.value;
              setParams(value === ALL ? {} : { profile: value });
            }}
          >
            <option value={ALL}>{t("resources.filter.all")}</option>
            {restProfiles.map((profile) => (
              <option key={profile.id} value={profile.id}>
                {profile.name}
              </option>
            ))}
          </Select>
        </div>
      )}
      {body}
      <Dialog open={previewing !== null} onOpenChange={(open) => !open && setPreviewing(null)}>
        <DialogContent className="max-h-[90vh] max-w-4xl overflow-y-auto">
          <DialogTitle>
            {t("resources.preview.title", { name: previewing?.name ?? "" })}
          </DialogTitle>
          <DialogDescription>{t("resources.preview.description")}</DialogDescription>
          {previewing && (
            <PreviewPanel
              key={`${previewing.profileId}/${previewing.name}`}
              profileId={previewing.profileId}
              name={previewing.name}
            />
          )}
        </DialogContent>
      </Dialog>
      <DeleteResourceDialog target={toDelete} onClose={() => setToDelete(null)} />
    </section>
  );
}
