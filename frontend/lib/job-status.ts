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

export function isTerminalJob(job: ReviewJob): boolean {
  const ui = toJobUiStatus(job.status);
  return ui === "success" || ui === "failed";
}
