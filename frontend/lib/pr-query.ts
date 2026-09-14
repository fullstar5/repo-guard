export type PrTab = "review" | "files" | "jobs";

export function parsePrTab(value: string | null): PrTab | null {
  if (value === "review" || value === "files" || value === "jobs") {
    return value;
  }
  return null;
}

function cloneSearch(current: { toString(): string }): URLSearchParams {
  return new URLSearchParams(current.toString());
}

function toHref(params: URLSearchParams): string {
  const query = params.toString();
  return query ? `?${query}` : "";
}

function clearHistoricalPin(params: URLSearchParams): void {
  params.delete("jobId");
  params.delete("finding");
}

/** Tab switches never keep a historical Review pin. */
export function prTabHref(
  current: { toString(): string },
  next: PrTab,
): string {
  const params = cloneSearch(current);
  params.set("tab", next);
  clearHistoricalPin(params);
  return toHref(params);
}

/** Explicit historical Review view, used when opening a row on Jobs. */
export function prJobHref(
  current: { toString(): string },
  jobId: number,
): string {
  const params = cloneSearch(current);
  params.set("tab", "review");
  params.set("jobId", String(jobId));
  params.delete("finding");
  return toHref(params);
}

/** Drop the pin and show the latest job on Review. */
export function prLatestReviewHref(current: { toString(): string }): string {
  const params = cloneSearch(current);
  params.set("tab", "review");
  clearHistoricalPin(params);
  return toHref(params);
}

/** Keep the current tab, but stop locking Review to an older job. */
export function prClearJobPinHref(current: { toString(): string }): string {
  const params = cloneSearch(current);
  clearHistoricalPin(params);
  return toHref(params);
}
