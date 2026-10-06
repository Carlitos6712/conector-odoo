import * as React from "react";
import { cn } from "@/lib/utils";

/** Native checkbox: keyboard and screen-reader behaviour come for free. */
export function Checkbox({ className, ...props }: Omit<React.ComponentProps<"input">, "type">) {
  return (
    <input
      type="checkbox"
      className={cn(
        "size-4 shrink-0 rounded border border-input accent-primary focus-visible:outline-2 focus-visible:outline-offset-1 focus-visible:outline-ring disabled:cursor-not-allowed disabled:opacity-50",
        className,
      )}
      {...props}
    />
  );
}
