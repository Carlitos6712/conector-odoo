export const MAX_CELL_LENGTH = 80;
const MAX_TITLE_LENGTH = 1000;

export interface Cell {
  /** What the table shows: plain text only, never markup. */
  text: string;
  /** The (bounded) complete value, present only when `text` was cut. */
  full?: string;
}

function stringify(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean" || typeof value === "bigint") {
    return String(value);
  }
  try {
    return JSON.stringify(value) ?? "—";
  } catch {
    return "[objeto]";
  }
}

/** Turns any JSON value from a remote system into a bounded, text-only table cell. */
export function formatCell(value: unknown): Cell {
  const text = stringify(value);
  if (text.length <= MAX_CELL_LENGTH) return { text };
  return {
    text: `${text.slice(0, MAX_CELL_LENGTH)}…`,
    full: text.slice(0, MAX_TITLE_LENGTH),
  };
}
