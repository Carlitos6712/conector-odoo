import type { BadgeProps } from "@/components/ui/badge";
import type { PropagationOutcome } from "@/features/records/types";

const VARIANT: Record<PropagationOutcome["action"], BadgeProps["variant"]> = {
  created: "success",
  updated: "info",
  deleted: "brand",
  skipped: "secondary",
  failed: "destructive",
};

/** Badge colour for what a bidirectional job did to the counterpart record. */
export const actionVariant = (action: PropagationOutcome["action"]): BadgeProps["variant"] =>
  VARIANT[action];
