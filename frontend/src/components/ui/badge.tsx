import { cva, type VariantProps } from "class-variance-authority";
import * as React from "react";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium",
  {
    variants: {
      variant: {
        default: "border-transparent bg-primary text-primary-foreground",
        brand: "border-brand-soft-foreground/20 bg-brand-soft text-brand-soft-foreground",
        secondary: "border-border bg-secondary text-secondary-foreground",
        outline: "text-foreground",
        destructive:
          "border-destructive-soft-foreground/25 bg-destructive-soft text-destructive-soft-foreground",
        success: "border-success-soft-foreground/25 bg-success-soft text-success-soft-foreground",
        warning: "border-warning-soft-foreground/25 bg-warning-soft text-warning-soft-foreground",
        info: "border-info-soft-foreground/25 bg-info-soft text-info-soft-foreground",
      },
    },
    defaultVariants: { variant: "secondary" },
  },
);

export interface BadgeProps
  extends React.ComponentProps<"span">, VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
