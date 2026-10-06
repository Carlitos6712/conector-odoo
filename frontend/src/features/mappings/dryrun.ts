import type { DryRunReport, Issue, MappingDoc } from "@/features/mappings/types";

/**
 * Turns a dry-run report into findings anchored on the definition, so they can be shown on the
 * rule that causes them. Rule errors name the rule by its target; value checks name the target
 * field they looked at. A finding that matches no rule is anchored at `target.<field>`.
 * The same problem hit by several sample records is reported once.
 */
export function dryRunIssues(definition: MappingDoc, report: DryRunReport): Issue[] {
  const ruleOf = (field: string): number =>
    definition.rules.findIndex(
      (rule) => rule.target === field || rule.target.split(".")[0] === field,
    );
  const found: Issue[] = [...report.definition_issues];
  for (const item of report.items) {
    for (const error of item.errors) {
      const index = ruleOf(error.rule_target);
      const path =
        index < 0
          ? `target.${error.rule_target}`
          : error.step_index === null
            ? `rules[${index}]`
            : `rules[${index}].expr.steps[${error.step_index}]`;
      found.push({ path, severity: "error", message: error.message });
    }
    for (const issue of item.validation) {
      const index = ruleOf(issue.path);
      found.push({
        ...issue,
        path: index < 0 ? `target.${issue.path}` : `rules[${index}]`,
      });
    }
  }
  const seen = new Set<string>();
  return found.filter((issue) => {
    const key = `${issue.path}|${issue.severity}|${issue.message}`;
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}
