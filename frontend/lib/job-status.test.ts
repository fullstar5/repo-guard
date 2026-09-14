import assert from "node:assert/strict";
import { test } from "node:test";

import {
  ACTIVE_JOB_REFETCH_MS,
  activeJobsRefetchInterval,
  isActiveJob,
} from "./job-status";
import type { ReviewJob } from "./api";

function job(status: ReviewJob["status"]): ReviewJob {
  return {
    id: 1,
    pull_request_id: 2,
    status,
    provider: "openrouter",
    model_name: "openrouter/free",
    total_files: 0,
    total_chunks: 0,
    error_message: null,
    result_summary: null,
    findings: [],
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

test("polls only while a job is pending or processing", () => {
  assert.equal(
    activeJobsRefetchInterval({ state: { data: [job("pending")] } }),
    ACTIVE_JOB_REFETCH_MS,
  );
  assert.equal(
    activeJobsRefetchInterval({ state: { data: [job("completed")] } }),
    false,
  );
  assert.equal(isActiveJob(job("processing")), true);
});
