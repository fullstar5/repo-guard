import type { ReviewJob, ReviewJobStatus } from "@/lib/api";

export type JobUiStatus = "pending" | "processing" | "success" | "failed";

export function toJobUiStatus(status: ReviewJobStatus | string): JobUiStatus {
  if (status === "completed" || status === "success") {
    return "success";
  }
  if (status === "processing" || status === "pending" || status === "failed") {
    return status;
  }
  return "failed";
}

export function isActiveJob(job: ReviewJob): boolean {
  return job.status === "pending" || job.status === "processing";
}

/** Poll while a job is queued or running so Review/Files don't sit on stale status. */
export const ACTIVE_JOB_REFETCH_MS = 4_000;

export function activeJobsRefetchInterval(query: {
  state: { data: ReviewJob[] | undefined };
}): number | false {
  return (query.state.data ?? []).some(isActiveJob) ? ACTIVE_JOB_REFETCH_MS : false;
}

export function isTerminalJob(job: ReviewJob): boolean {
  const ui = toJobUiStatus(job.status);
  return ui === "success" || ui === "failed";
}
