"use client";

import Link from "next/link";

import { InlineStatus } from "@/components/empty-state";
import {
  LeanTable,
  LeanTableCell,
  LeanTableHead,
  LeanTableHeader,
  LeanTableRow,
  Table,
  TableBody,
} from "@/components/lean-table";
import { JobStatusChip } from "@/components/status-badges";
import type { ReviewJob } from "@/lib/api";
import { formatDuration, formatRelativeTime } from "@/lib/format";
import { isActiveJob, isTerminalJob, toJobUiStatus } from "@/lib/job-status";
import { cn } from "@/lib/utils";

export function ReviewJobsTable({
  jobs,
  selectedJobId,
  hrefForJob,
  onSelectJob,
  onRetry,
  retryDisabled,
  retryPending,
}: {
  jobs: ReviewJob[];
  selectedJobId?: number;
  hrefForJob: (job: ReviewJob) => string;
  onSelectJob?: (job: ReviewJob) => void;
  onRetry: () => void;
  retryDisabled: boolean;
  retryPending: boolean;
}) {
  if (jobs.length === 0) {
    return <InlineStatus>No review jobs yet.</InlineStatus>;
  }

  return (
    <LeanTable>
      <Table>
        <LeanTableHeader>
          <LeanTableRow>
            <LeanTableHead>ID</LeanTableHead>
            <LeanTableHead>Status</LeanTableHead>
            <LeanTableHead>Findings</LeanTableHead>
            <LeanTableHead>Duration</LeanTableHead>
            <LeanTableHead>Updated</LeanTableHead>
            <LeanTableHead className="w-20" />
          </LeanTableRow>
        </LeanTableHeader>
        <TableBody>
          {jobs.map((job) => {
            const ui = toJobUiStatus(job.status);
            const showRetry = isTerminalJob(job);
            return (
              <LeanTableRow
                key={job.id}
                className={selectedJobId === job.id ? "bg-[#27272a]/80" : undefined}
              >
                <LeanTableCell>
                  <Link
                    href={hrefForJob(job)}
                    onClick={() => onSelectJob?.(job)}
                    className="font-mono text-sm text-[#fafafa] hover:text-[#67e8f9] focus-visible:text-[#67e8f9] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
                  >
                    job_{job.id}
                  </Link>
                </LeanTableCell>
                <LeanTableCell>
                  <JobStatusChip status={job.status} />
                </LeanTableCell>
                <LeanTableCell className="tabular-nums text-[#a1a1aa]">
                  {isActiveJob(job) ? "—" : job.findings.length}
                </LeanTableCell>
                <LeanTableCell className="tabular-nums text-[#a1a1aa]">
                  {isTerminalJob(job)
                    ? formatDuration(job.created_at, job.updated_at)
                    : "—"}
                </LeanTableCell>
                <LeanTableCell className="text-[#a1a1aa]">
                  {ui === "pending" ? "Queued" : formatRelativeTime(job.updated_at)}
                </LeanTableCell>
                <LeanTableCell className="text-right">
                  {showRetry ? (
                    <button
                      type="button"
                      onClick={onRetry}
                      disabled={retryDisabled || retryPending}
                      className={cn(
                        "rounded-sm text-sm text-[#a1a1aa] hover:text-[#fafafa] focus-visible:text-[#fafafa] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none",
                        (retryDisabled || retryPending) && "cursor-not-allowed opacity-40",
                      )}
                      aria-label={`Retry job ${job.id}`}
                    >
                      Retry
                    </button>
                  ) : null}
                </LeanTableCell>
              </LeanTableRow>
            );
          })}
        </TableBody>
      </Table>
    </LeanTable>
  );
}
