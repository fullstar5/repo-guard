/** Parse a route param that must be a positive integer id. */
export function parsePositiveInt(value: string | undefined | null): number | null {
  if (value == null || !/^[1-9]\d*$/.test(value)) {
    return null;
  }
  const parsed = Number(value);
  return Number.isSafeInteger(parsed) ? parsed : null;
}
