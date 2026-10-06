export interface CheckpointInfo {
  /** `forward` (A to B) or `reverse` (B to A) for bidirectional jobs. */
  pass: string;
  /** Last processed source record id: a resume skips up to it. */
  lastId: string | null;
  done: boolean;
  maxUpdatedAt: string | null;
}

/**
 * The runner stores `pass`, `last_id`, `done` and `max_updated_at` (`SyncRunner`); anything
 * else, or a value of the wrong type, is ignored. `null` when nothing useful was saved.
 */
export function describeCheckpoint(checkpoint: Record<string, unknown>): CheckpointInfo | null {
  const { pass, last_id: lastId, done, max_updated_at: maxUpdatedAt } = checkpoint;
  if (typeof pass !== "string") return null;
  return {
    pass,
    lastId:
      typeof lastId === "string" ? lastId : typeof lastId === "number" ? String(lastId) : null,
    done: done === true,
    maxUpdatedAt: typeof maxUpdatedAt === "string" ? maxUpdatedAt : null,
  };
}
