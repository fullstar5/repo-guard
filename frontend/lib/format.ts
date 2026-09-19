const MINUTE = 60_000;
const HOUR = 60 * MINUTE;
const DAY = 24 * HOUR;

function startOfLocalDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** Compact relative timestamp for table columns, matching the product mocks. */
export function formatRelativeTime(value: string | Date | null | undefined, now = new Date()): string {
  if (!value) {
    return "—";
  }
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }

  const diff = now.getTime() - date.getTime();
  if (diff < MINUTE) {
    return "Just now";
  }
  if (diff < HOUR) {
    const minutes = Math.max(1, Math.round(diff / MINUTE));
    return minutes === 1 ? "1 min ago" : `${minutes} min ago`;
  }
  if (diff < DAY) {
    const hours = Math.max(1, Math.round(diff / HOUR));
    return hours === 1 ? "1 hour ago" : `${hours} hours ago`;
  }

  const dayDiff = Math.round(
    (startOfLocalDay(now) - startOfLocalDay(date)) / DAY,
  );
  if (dayDiff === 1) {
    return "Yesterday";
  }
  if (dayDiff < 7) {
    return `${dayDiff} days ago`;
  }
  const weeks = Math.round(dayDiff / 7);
  if (weeks < 5) {
    return weeks === 1 ? "1 week ago" : `${weeks} weeks ago`;
  }
  const months = Math.round(dayDiff / 30);
  if (months < 12) {
    return months <= 1 ? "1 month ago" : `${months} months ago`;
  }
  const years = Math.max(1, Math.round(dayDiff / 365));
  return years === 1 ? "1 year ago" : `${years} years ago`;
}

/** Job duration as m:ss, used only for terminal jobs. */
export function formatDuration(startedAt: string, endedAt: string): string {
  const start = new Date(startedAt).getTime();
  const end = new Date(endedAt).getTime();
  if (Number.isNaN(start) || Number.isNaN(end) || end < start) {
    return "—";
  }
  const totalSeconds = Math.floor((end - start) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${seconds.toString().padStart(2, "0")}`;
}

export function initialsFromLogin(login: string): string {
  const cleaned = login.trim();
  if (!cleaned) {
    return "CG";
  }
  const parts = cleaned.split(/[-_.\s]+/).filter(Boolean);
  if (parts.length >= 2) {
    return (parts[0][0] + parts[1][0]).toUpperCase();
  }
  return cleaned.slice(0, 2).toUpperCase();
}
