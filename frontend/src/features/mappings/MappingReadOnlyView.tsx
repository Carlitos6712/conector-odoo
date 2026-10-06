import { History } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Link } from "react-router-dom";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { describeExpr, stateFromDefinition } from "@/features/mappings/model";
import type { StoredMapping } from "@/features/mappings/types";

/** What operators see: the saved rules and the JSON, with nothing to change. */
export function MappingReadOnlyView({ stored }: { stored: StoredMapping }) {
  const { t } = useTranslation();
  const { definition } = stored;
  const rules = stateFromDefinition(definition).rules;
  return (
    <section className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <h1 className="text-2xl font-semibold">
          {t("mappings.editor.titleView", { name: stored.name })}
        </h1>
        <div className="flex items-center gap-2">
          <Badge variant="outline">v{stored.version}</Badge>
          <Button variant="outline" asChild>
            <Link to={`/mappings/${encodeURIComponent(stored.name)}/versions`}>
              <History aria-hidden className="size-4" />
              {t("mappings.editor.history")}
            </Link>
          </Button>
        </div>
      </div>
      <p className="text-sm text-muted-foreground">
        {t("mappings.editor.readOnly", {
          source: definition.source_resource,
          target: definition.target_resource,
        })}
      </p>
      <Table aria-label={t("mappings.editor.rules.heading")}>
        <TableHeader>
          <TableRow>
            <TableHead>{t("mappings.editor.rules.target")}</TableHead>
            <TableHead>{t("mappings.editor.readOnlyExpression")}</TableHead>
            <TableHead>{t("mappings.editor.rules.required")}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {rules.map((rule) => (
            <TableRow key={rule.key}>
              <TableCell className="font-mono text-xs">{rule.target}</TableCell>
              <TableCell className="break-all font-mono text-xs">
                {describeExpr(rule.expr)}
              </TableCell>
              <TableCell>{rule.required ? t("common.yes") : t("common.no")}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <pre className="max-h-[32rem] overflow-auto rounded-md border bg-muted p-3 text-xs">
        {JSON.stringify(definition, null, 2)}
      </pre>
    </section>
  );
}
