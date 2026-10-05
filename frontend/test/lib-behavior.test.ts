import { describe, expect, it } from "vitest";

import { parsePatch, snippetAround, findingsToHighlights } from "@/components/diff-view";
import { isInitialAuthPending } from "@/lib/auth-session";
import { formatDuration, formatRelativeTime, initialsFromLogin } from "@/lib/format";
import { isActiveJob, isTerminalJob, toJobUiStatus } from "@/lib/job-status";
import {
  prClearJobPinHref,
  prJobHref,
  prLatestReviewHref,
  prTabHref,
  parsePrTab,
} from "@/lib/pr-query";
import {
  findingFileHref,
  findingLocationLabel,
  findingsForFile,
  isHistoricalJobPin,
  latestReviewJob,
  pickSelectedReviewJob,
  resolveDisplayedReviewJob,
  resolveFindingFile,
} from "@/lib/review-findings";
import { reviewModelLabel } from "@/lib/review-models";
import type { PullRequestFile, ReviewFinding, ReviewJob } from "@/lib/api";

const now = new Date("2026-06-15T12:00:00Z");

function finding(partial: Partial<ReviewFinding> & Pick<ReviewFinding, "id">): ReviewFinding {
  return {
    severity: "medium",
    summary: "issue",
    file_path: "src/a.py",
    pr_file_id: null,
    start_line: null,
    end_line: null,
    suggestion: null,
    created_at: "2026-06-01T00:00:00Z",
    updated_at: "2026-06-01T00:00:00Z",
    ...partial,
  };
}

function job(partial: Partial<ReviewJob> & Pick<ReviewJob, "id" | "status" | "updated_at">): ReviewJob {
  return {
    pull_request_id: 8,
    provider: "openrouter",
    model_name: "openrouter/free",
    total_files: 1,
    total_chunks: 1,
    error_message: null,
    result_summary: null,
    findings: [],
    created_at: "2026-06-01T00:00:00Z",
    ...partial,
  };
}

function file(partial: Partial<PullRequestFile> & Pick<PullRequestFile, "id" | "filename">): PullRequestFile {
  return {
    previous_filename: null,
    status: "modified",
    additions: 1,
    deletions: 0,
    changes: 1,
    ...partial,
  };
}

describe("job pin and latest review (option A)", () => {
  const jobs = [
    job({
      id: 1,
      status: "completed",
      updated_at: "2026-06-01T00:00:00Z",
      result_summary: "old",
    }),
    job({
      id: 2,
      status: "failed",
      updated_at: "2026-06-10T00:00:00Z",
      result_summary: "newer failure",
    }),
    job({
      id: 3,
      status: "completed",
      updated_at: "2026-06-05T00:00:00Z",
      result_summary: "latest completed",
    }),
    job({
      id: 4,
      status: "pending",
      updated_at: "2026-06-14T00:00:00Z",
    }),
  ];

  it("treats a non-empty jobId as a historical pin", () => {
    expect(isHistoricalJobPin(null)).toBe(false);
    expect(isHistoricalJobPin("")).toBe(false);
    expect(isHistoricalJobPin("3")).toBe(true);
    expect(pickSelectedReviewJob(jobs, "nope")).toBeUndefined();
    expect(pickSelectedReviewJob(jobs, "3")?.id).toBe(3);
  });

  it("defaults to the newest completed job, otherwise the newest job", () => {
    expect(latestReviewJob(jobs)?.id).toBe(3);
    expect(latestReviewJob(jobs.filter((item) => item.status !== "completed"))?.id).toBe(4);
    expect(latestReviewJob([])).toBeUndefined();
  });

  it("shows the pinned job when it exists and otherwise falls back to latest", () => {
    expect(resolveDisplayedReviewJob(jobs, "1")?.id).toBe(1);
    expect(resolveDisplayedReviewJob(jobs, null)?.id).toBe(3);
    expect(resolveDisplayedReviewJob(jobs, "99")?.id).toBe(3);
  });

  it("drops the historical pin when switching tabs or returning to latest", () => {
    const current = new URLSearchParams("tab=jobs&jobId=1&finding=9&q=keep");
    expect(parsePrTab("files")).toBe("files");
    expect(parsePrTab("nope")).toBeNull();
    expect(prTabHref(current, "files")).toBe("?tab=files&q=keep");
    expect(prJobHref(current, 2)).toBe("?tab=review&jobId=2&q=keep");
    expect(prLatestReviewHref(current)).toBe("?tab=review&q=keep");
    expect(prClearJobPinHref(current)).toBe("?tab=jobs&q=keep");
  });
});

describe("findings helpers", () => {
  const files = [
    file({ id: 10, filename: "src/a.py" }),
    file({ id: 11, filename: "src/b.py" }),
  ];

  it("resolves a file by id before path and builds a deep link", () => {
    const byId = finding({ id: 1, pr_file_id: 11, file_path: "src/a.py", start_line: 4, end_line: 6 });
    expect(resolveFindingFile(files, byId)?.id).toBe(11);
    expect(findingFileHref(2, 8, files, byId, 3)).toBe(
      "/repositories/2/pull-requests/8/files/11?jobId=3#L4",
    );
    expect(findingLocationLabel(byId)).toBe("src/a.py:4-6");

    const missing = finding({ id: 2, file_path: "gone.py", pr_file_id: 99 });
    expect(findingFileHref(2, 8, files, missing, 3)).toBeNull();
    expect(findingLocationLabel(finding({ id: 3, file_path: null }))).toBe("Unknown file");
  });

  it("keeps findings that match the file id or path", () => {
    const rows = [
      finding({ id: 1, pr_file_id: 10, file_path: "other.py" }),
      finding({ id: 2, pr_file_id: null, file_path: "src/a.py" }),
      finding({ id: 3, pr_file_id: 11, file_path: "src/b.py" }),
    ];
    expect(findingsForFile(rows, files[0]).map((item) => item.id)).toEqual([1, 2]);
  });
});

describe("job status, models, and time", () => {
  it("maps completed to success and unknown values to failed", () => {
    expect(toJobUiStatus("completed")).toBe("success");
    expect(toJobUiStatus("success")).toBe("success");
    expect(toJobUiStatus("pending")).toBe("pending");
    expect(toJobUiStatus("partial")).toBe("failed");
    const active = job({ id: 1, status: "processing", updated_at: now.toISOString() });
    const done = job({ id: 2, status: "completed", updated_at: now.toISOString() });
    expect(isActiveJob(active)).toBe(true);
    expect(isTerminalJob(active)).toBe(false);
    expect(isTerminalJob(done)).toBe(true);
  });

  it("labels allowlisted models and leaves unknown ids unchanged", () => {
    expect(reviewModelLabel("openrouter/free")).toBe("Free router");
    expect(reviewModelLabel("nvidia/nemotron-3-ultra-550b-a55b:free")).toBe(
      "Nemotron 3 Ultra",
    );
    expect(reviewModelLabel("custom/model")).toBe("custom/model");
  });

  it("formats relative time, duration, and initials from a fixed clock", () => {
    expect(formatRelativeTime(null, now)).toBe("—");
    expect(formatRelativeTime("not-a-date", now)).toBe("—");
    expect(formatRelativeTime(new Date(now.getTime() - 30_000), now)).toBe("Just now");
    expect(formatRelativeTime(new Date(now.getTime() - 60_000), now)).toBe("1 min ago");
    expect(formatRelativeTime(new Date(now.getTime() - 3_600_000), now)).toBe("1 hour ago");
    expect(formatDuration("2026-06-15T12:00:00Z", "2026-06-15T12:01:05Z")).toBe("1:05");
    expect(formatDuration("2026-06-15T12:02:00Z", "2026-06-15T12:01:00Z")).toBe("—");
    expect(initialsFromLogin("octo-cat")).toBe("OC");
    expect(initialsFromLogin("")).toBe("CG");
  });

  it("only treats the first auth fetch as the full-screen gate", () => {
    expect(isInitialAuthPending({ isPending: true, isFetched: false })).toBe(true);
    expect(isInitialAuthPending({ isPending: true, isFetched: true })).toBe(false);
    expect(isInitialAuthPending({ isPending: false, isFetched: true })).toBe(false);
  });
});

describe("diff parsing", () => {
  const patch = [
    "@@ -1,2 +1,3 @@",
    " context",
    "-old",
    "+new",
    "+extra",
  ].join("\n");

  it("assigns old and new line numbers", () => {
    const lines = parsePatch(patch);
    const added = lines.filter((line) => line.kind === "add");
    expect(added.map((line) => line.newLine)).toEqual([2, 3]);
    expect(lines.find((line) => line.kind === "del")?.oldLine).toBe(2);
    expect(lines.find((line) => line.kind === "ctx")?.newLine).toBe(1);
  });

  it("returns a window around the new-file lines", () => {
    const snippet = snippetAround(patch, 2, 2, 1);
    expect(snippet.map((line) => line.text)).toEqual([" context", "-old", "+new", "+extra"]);
    expect(snippetAround(null, 1, 1)).toEqual([]);
  });

  it("highlights only findings that have a start line", () => {
    const highlights = findingsToHighlights([
      finding({ id: 1, start_line: null }),
      finding({ id: 2, start_line: 4, end_line: null }),
    ]);
    expect(highlights).toEqual([
      {
        startLine: 4,
        endLine: 4,
        finding: expect.objectContaining({ id: 2 }),
      },
    ]);
  });
});
