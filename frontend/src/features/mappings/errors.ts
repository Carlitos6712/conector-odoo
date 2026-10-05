import { ApiError } from "@/api/client";
import type { Issue, Severity } from "@/features/mappings/types";
import { describeResourceError } from "@/features/resources/errors";

export type MappingAction = "save" | "delete" | "dryRun" | "suggest" | "load";

export interface DescribedMappingError {
  messageKey: string;
  params?: Record<string, unknown>;
  /** Findings anchored at definition paths, to show on the offending rule. */
  issues: Issue[];
  /** Server text worth showing (remote failures); masked server-side, clipped here. */
  detail?: string;
}

const MAX_DETAIL = 300;
// Codec errors start with the offending path: `rules[2].expr.steps[1]: unknown step type 'x'`.
const PATH_PREFIX = /^((?:rules|target|name|source_resource|target_resource)[\w.[\]]*): (.*)$/s;

const clip = (text: string): string | undefined =>
  text ? (text.length > MAX_DETAIL ? `${text.slice(0, MAX_DETAIL)}…` : text) : undefined;

function structuredIssues(extra: unknown): Issue[] {
  if (!Array.isArray(extra)) return [];
  return extra.flatMap((raw: unknown): Issue[] => {
    if (!raw || typeof raw !== "object") return [];
    const { path, severity, message } = raw as Record<string, unknown>;
    if (typeof path !== "string" || typeof message !== "string") return [];
    return [{ path, severity: severity === "warning" ? "warning" : "error", message }];
  });
}

function issuesFromDetail(detail: string): Issue[] {
  return detail.split("; ").flatMap((part): Issue[] => {
    const match = PATH_PREFIX.exec(part);
    return match ? [{ path: match[1]!, severity: "error" as Severity, message: match[2]! }] : [];
  });
}

/** Maps an API failure to translation keys plus the path-anchored findings it carries. */
export function describeMappingError(error: unknown, action: MappingAction): DescribedMappingError {
  if (error instanceof ApiError) {
    if (error.status === 409) {
      return {
        messageKey: action === "delete" ? "mappings.errors.inUse" : "mappings.errors.conflict",
        issues: [],
      };
    }
    if (error.status === 422) {
      const issues = structuredIssues(error.extra.issues);
      const found = issues.length > 0 ? issues : issuesFromDetail(error.detail);
      return {
        messageKey: "mappings.errors.validation",
        issues: found,
        detail: found.length === 0 ? clip(error.detail) : undefined,
      };
    }
    if (error.status === 404 && error.code === "not_found") {
      return { messageKey: "mappings.errors.notFound", issues: [] };
    }
  }
  return { ...describeResourceError(error, "preview"), issues: [] };
}
