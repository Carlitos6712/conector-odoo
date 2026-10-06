import { useTranslation } from "react-i18next";
import type { Issue } from "@/features/mappings/types";
import { cn } from "@/lib/utils";

/** Findings with the definition path they point at (server text, rendered as plain text). */
export function IssueList({
  issues,
  className,
  label,
}: {
  issues: readonly Issue[];
  className?: string;
  label?: string;
}) {
  const { t } = useTranslation();
  if (issues.length === 0) return null;
  return (
    <ul aria-label={label} className={cn("flex flex-col gap-1 text-sm", className)}>
      {issues.map((issue, index) => (
        <li
          key={`${issue.path}-${index}`}
          className={
            issue.severity === "error" ? "text-destructive" : "text-warning-soft-foreground"
          }
        >
          <span className="font-medium">{t(`mappings.issues.${issue.severity}`)}</span>{" "}
          <code className="break-all text-xs">{issue.path}</code>: {issue.message}
        </li>
      ))}
    </ul>
  );
}
