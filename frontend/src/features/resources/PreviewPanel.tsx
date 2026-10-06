import { RefreshCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Loading } from "@/components/Loading";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { describeResourceError } from "@/features/resources/errors";
import { formatCell } from "@/features/resources/format";
import { usePreview } from "@/features/resources/hooks";
import type { FieldSpec, PreviewRecord } from "@/features/resources/types";

const MAX_COLUMNS = 15;

function columnsOf(records: readonly PreviewRecord[]): string[] {
  const seen = new Set<string>();
  for (const record of records) for (const key of Object.keys(record.fields)) seen.add(key);
  return [...seen];
}

export function SchemaTable({ fields, label }: { fields: readonly FieldSpec[]; label?: string }) {
  const { t } = useTranslation();
  return (
    <Table aria-label={label ?? t("resources.preview.schema")}>
      <TableHeader>
        <TableRow>
          <TableHead>{t("resources.preview.field")}</TableHead>
          <TableHead>{t("resources.preview.type")}</TableHead>
          <TableHead>{t("resources.preview.required")}</TableHead>
          <TableHead>{t("resources.preview.relation")}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {fields.map((field) => (
          <TableRow key={field.name}>
            <TableCell className="font-mono text-xs">{field.name}</TableCell>
            <TableCell>{field.type}</TableCell>
            <TableCell>{field.required ? t("common.yes") : t("common.no")}</TableCell>
            <TableCell className="font-mono text-xs">{field.relation ?? "—"}</TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

/** Runs the preview when mounted: a few live records plus the inferred schema. Text only. */
export function PreviewPanel({ profileId, name }: { profileId: number; name: string }) {
  const { t } = useTranslation();
  const preview = usePreview(profileId, name);

  if (preview.isPending) return <Loading />;
  if (preview.isError) {
    const described = describeResourceError(preview.error, "preview");
    return (
      <div role="alert" className="flex flex-col items-start gap-2 text-sm">
        <p className="text-destructive">{t(described.messageKey, described.params)}</p>
        {described.detail && (
          <p className="break-words text-muted-foreground">{described.detail}</p>
        )}
        <Button variant="outline" size="sm" onClick={() => void preview.refetch()}>
          {t("common.retry")}
        </Button>
      </div>
    );
  }

  const { records, schema } = preview.data;
  const columns = columnsOf(records);
  const shown = columns.slice(0, MAX_COLUMNS);
  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-2">
        <div className="flex items-center justify-between gap-2">
          <h3 className="font-medium">{t("resources.preview.records")}</h3>
          <Button
            variant="ghost"
            size="sm"
            disabled={preview.isFetching}
            onClick={() => void preview.refetch()}
          >
            <RefreshCw aria-hidden className="size-4" />
            {t("resources.preview.refresh")}
          </Button>
        </div>
        {records.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("resources.preview.noRecords")}</p>
        ) : (
          <>
            <Table aria-label={t("resources.preview.records")}>
              <TableHeader>
                <TableRow>
                  {shown.map((column) => (
                    <TableHead key={column}>{column}</TableHead>
                  ))}
                </TableRow>
              </TableHeader>
              <TableBody>
                {records.map((record, index) => (
                  <TableRow key={record.id ?? index}>
                    {shown.map((column) => {
                      const cell = formatCell(record.fields[column]);
                      return (
                        <TableCell key={column} title={cell.full} className="max-w-xs break-words">
                          {cell.text}
                        </TableCell>
                      );
                    })}
                  </TableRow>
                ))}
              </TableBody>
            </Table>
            <p className="flex flex-wrap items-center gap-x-3 text-xs text-muted-foreground">
              <span>{t("resources.preview.showing", { count: records.length })}</span>
              <Link
                className="font-medium text-primary underline"
                to={`/records?profile=${profileId}&resource=${encodeURIComponent(name)}`}
              >
                {t("resources.preview.viewAll")}
              </Link>
            </p>
            {columns.length > shown.length && (
              <p className="text-xs text-muted-foreground">
                {t("resources.preview.moreColumns", { count: columns.length - shown.length })}
              </p>
            )}
          </>
        )}
      </section>
      <section className="flex flex-col gap-2">
        <h3 className="font-medium">{t("resources.preview.schemaTitle")}</h3>
        {schema.fields.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t("resources.preview.noSchema")}</p>
        ) : (
          <SchemaTable fields={schema.fields} />
        )}
      </section>
    </div>
  );
}
