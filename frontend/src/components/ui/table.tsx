import * as React from "react";
import { cn } from "@/lib/utils";

export function Table({ className, ...props }: React.ComponentProps<"table">) {
  return (
    <div className="w-full overflow-x-auto rounded-lg border bg-card shadow-soft">
      <table className={cn("w-full caption-bottom text-sm", className)} {...props} />
    </div>
  );
}

export const TableHeader = (props: React.ComponentProps<"thead">) => (
  <thead className="bg-brand-soft/60 [&_tr]:border-b" {...props} />
);

export const TableBody = (props: React.ComponentProps<"tbody">) => (
  <tbody className="[&_tr:last-child]:border-0" {...props} />
);

export function TableRow({ className, ...props }: React.ComponentProps<"tr">) {
  return (
    <tr
      className={cn("border-b transition-colors even:bg-muted/40 hover:bg-accent/50", className)}
      {...props}
    />
  );
}

export function TableHead({ className, ...props }: React.ComponentProps<"th">) {
  return (
    <th
      scope="col"
      className={cn(
        "h-10 px-3 text-left align-middle text-xs font-semibold uppercase tracking-wide text-brand-soft-foreground",
        className,
      )}
      {...props}
    />
  );
}

export function TableCell({ className, ...props }: React.ComponentProps<"td">) {
  return <td className={cn("px-3 py-2 align-middle", className)} {...props} />;
}
