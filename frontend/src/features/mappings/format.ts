/** Local date and time of an ISO timestamp; the raw text when it cannot be parsed. */
export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? iso : date.toLocaleString("es-ES");
}
