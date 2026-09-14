import { Loader2 } from "lucide-react";

import { cn } from "@/lib/utils";
import type { ReviewFindingSeverity } from "@/lib/api";
import { toJobUiStatus, type JobUiStatus } from "@/lib/job-status";

const SEVERITY_CLASS: Record<ReviewFindingSeverity, string> = {
  critical: "bg-[#7f1d1d]/80 text-[#fecaca] ring-1 ring-[#7f1d1d]",
  high: "bg-[#9a3412]/80 text-[#fed7aa] ring-1 ring-[#9a3412]",
  medium: "bg-[#854d0e]/70 text-[#fde68a] ring-1 ring-[#854d0e]",
  low: "bg-[#27272a] text-[#d4d4d8] ring-1 ring-[#3f3f46]",
};

export function SeverityBadge({
  severity,
  className,
}: {
  severity: ReviewFindingSeverity;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2 py-0.5 text-[11px] font-medium uppercase tracking-wide",
        SEVERITY_CLASS[severity],
        className,
      )}
    >
      {severity}
    </span>
  );
}

const SEVERITY_COUNT_CLASS: Record<ReviewFindingSeverity, string> = {
  critical: "bg-[#7f1d1d]/80 text-[#fecaca]",
  high: "bg-[#9a3412]/80 text-[#fed7aa]",
  medium: "bg-[#854d0e]/70 text-[#fde68a]",
  low: "bg-[#27272a] text-[#d4d4d8]",
};

export function SeverityCountChip({
  severity,
  count,
}: {
  severity: ReviewFindingSeverity;
  count: number;
}) {
  if (count <= 0) {
    return null;
  }
  const label = severity.charAt(0).toUpperCase() + severity.slice(1);
  return (
    <span
      className={cn(
        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium",
        SEVERITY_COUNT_CLASS[severity],
      )}
    >
      {count} {label}
    </span>
  );
}

export function VisibilityBadge({ isPrivate }: { isPrivate: boolean }) {
  if (isPrivate) {
    return (
      <span className="inline-flex rounded-full bg-[#713f12]/80 px-2.5 py-0.5 text-xs font-medium text-[#fde68a] ring-1 ring-[#854d0e]/80">
        Private
      </span>
    );
  }
  return (
    <span className="inline-flex rounded-full bg-[#14532d]/70 px-2.5 py-0.5 text-xs font-medium text-[#86efac] ring-1 ring-[#166534]/80">
      Public
    </span>
  );
}

export function PullRequestStateBadge({
  state,
  isDraft,
}: {
  state: string;
  isDraft: boolean;
}) {
  if (isDraft) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-[#27272a] px-2.5 py-0.5 text-xs font-medium text-[#a1a1aa] ring-1 ring-[#3f3f46]">
        <span className="size-1.5 rounded-full bg-[#a1a1aa]" />
        Draft
      </span>
    );
  }
  const open = state.toLowerCase() === "open";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1",
        open
          ? "bg-[#14532d]/70 text-[#86efac] ring-[#166534]/80"
          : "bg-[#7f1d1d]/70 text-[#fca5a5] ring-[#991b1b]/80",
      )}
    >
      <span
        className={cn("size-1.5 rounded-full", open ? "bg-[#4ade80]" : "bg-[#f87171]")}
      />
      {open ? "Open" : "Closed"}
    </span>
  );
}

const JOB_STATUS_CLASS: Record<
  JobUiStatus,
  { label: string; className: string; dot: string }
> = {
  pending: {
    label: "Pending",
    className: "bg-[#27272a] text-[#a1a1aa]",
    dot: "bg-[#a1a1aa]",
  },
  processing: {
    label: "Processing...",
    className: "bg-[#164e63]/50 text-[#67e8f9]",
    dot: "bg-[#22d3ee]",
  },
  success: {
    label: "Success",
    className: "bg-[#14532d]/50 text-[#86efac]",
    dot: "bg-[#4ade80]",
  },
  failed: {
    label: "Failed",
    className: "bg-[#7f1d1d]/45 text-[#fca5a5]",
    dot: "bg-[#f87171]",
  },
};

export function JobStatusChip({
  status,
}: {
  status: ReviewJobStatusFromApi;
}) {
  const ui = toJobUiStatus(status);
  const meta = JOB_STATUS_CLASS[ui];
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium",
        meta.className,
      )}
    >
      {ui === "processing" ? (
        <Loader2 className="size-3 animate-spin" aria-hidden="true" />
      ) : (
        <span className={cn("size-1.5 rounded-full", meta.dot)} />
      )}
      {meta.label}
    </span>
  );
}

type ReviewJobStatusFromApi = string;
