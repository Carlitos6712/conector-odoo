import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

export interface StepItem {
  id: string;
  label: string;
}

/** Progress indicator of a wizard: completed, current (`aria-current`) and upcoming steps. */
export function Steps({
  items,
  current,
  label,
}: {
  items: readonly StepItem[];
  current: number;
  label: string;
}) {
  return (
    <nav aria-label={label}>
      <ol className="flex flex-wrap gap-x-6 gap-y-2">
        {items.map((item, index) => {
          const done = index < current;
          return (
            <li
              key={item.id}
              aria-current={index === current ? "step" : undefined}
              className={cn(
                "flex items-center gap-2 text-sm",
                index === current ? "font-semibold" : "text-muted-foreground",
              )}
            >
              <span
                aria-hidden
                className={cn(
                  "flex size-6 items-center justify-center rounded-full border text-xs",
                  index === current && "border-primary bg-primary text-primary-foreground",
                  done && "border-success bg-success text-success-foreground",
                )}
              >
                {done ? <Check className="size-3" /> : index + 1}
              </span>
              {item.label}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
