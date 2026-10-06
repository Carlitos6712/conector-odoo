import * as React from "react";
import { cn } from "@/lib/utils";

interface TabsContextValue {
  value: string;
  onValueChange: (value: string) => void;
  baseId: string;
}

const TabsContext = React.createContext<TabsContextValue | null>(null);

function useTabs(): TabsContextValue {
  const context = React.useContext(TabsContext);
  if (!context) throw new Error("Tabs components must be rendered inside <Tabs>");
  return context;
}

/** Controlled tabs following the WAI-ARIA tabs pattern (arrow keys move between tabs). */
export function Tabs({
  value,
  onValueChange,
  children,
}: {
  value: string;
  onValueChange: (value: string) => void;
  children: React.ReactNode;
}) {
  const baseId = React.useId();
  return (
    <TabsContext.Provider value={{ value, onValueChange, baseId }}>
      <div className="flex flex-col gap-4">{children}</div>
    </TabsContext.Provider>
  );
}

export function TabsList({ label, children }: { label: string; children: React.ReactNode }) {
  const ref = React.useRef<HTMLDivElement>(null);

  function onKeyDown(event: React.KeyboardEvent) {
    const step = event.key === "ArrowRight" ? 1 : event.key === "ArrowLeft" ? -1 : 0;
    if (step === 0 || !ref.current) return;
    const tabs = [...ref.current.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    const current = tabs.findIndex((tab) => tab === document.activeElement);
    const next = tabs[(current + step + tabs.length) % tabs.length];
    if (next) {
      event.preventDefault();
      next.focus();
      next.click();
    }
  }

  return (
    // eslint-disable-next-line jsx-a11y/interactive-supports-focus -- the focusable children are the tabs
    <div
      ref={ref}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className="inline-flex w-fit gap-1 rounded-lg bg-brand-soft p-1"
    >
      {children}
    </div>
  );
}

export function TabsTrigger({ value, children }: { value: string; children: React.ReactNode }) {
  const context = useTabs();
  const selected = context.value === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${context.baseId}-tab-${value}`}
      aria-selected={selected}
      aria-controls={`${context.baseId}-panel-${value}`}
      tabIndex={selected ? 0 : -1}
      onClick={() => context.onValueChange(value)}
      className={cn(
        "rounded-md px-3 py-1.5 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
        selected
          ? "bg-primary text-primary-foreground shadow-soft"
          : "text-brand-soft-foreground hover:bg-accent",
      )}
    >
      {children}
    </button>
  );
}

export function TabsContent({ value, children }: { value: string; children: React.ReactNode }) {
  const context = useTabs();
  if (context.value !== value) return null;
  return (
    <div
      role="tabpanel"
      id={`${context.baseId}-panel-${value}`}
      aria-labelledby={`${context.baseId}-tab-${value}`}
    >
      {children}
    </div>
  );
}
