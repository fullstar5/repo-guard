"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { snippetAround } from "@/components/diff-view";
import { SeverityBadge, SeverityCountChip } from "@/components/status-badges";
import { InlineStatus } from "@/components/empty-state";
import { getPullRequestFile, type PullRequestFile, type ReviewFinding, type ReviewFindingSeverity, type ReviewJob } from "@/lib/api";
import { formatRelativeTime } from "@/lib/format";
import { toJobUiStatus } from "@/lib/job-status";
import {
  SEVERITY_ORDER,
  findingFileHref,
  findingLocationLabel,
  resolveFindingFile,
} from "@/lib/review-findings";
import { cn } from "@/lib/utils";

const SEVERITY_FILTERS: Array<ReviewFindingSeverity | "all"> = [
  "all",
  "critical",
  "high",
  "medium",
  "low",
];

export function ReviewWorkspace({
  job,
  files,
  repositoryId,
  pullRequestId,
}: {
  job: ReviewJob;
  files: PullRequestFile[];
  repositoryId: number;
  pullRequestId: number;
}) {
  const [severity, setSeverity] = useState<ReviewFindingSeverity | "all">("all");
  const [selectedId, setSelectedId] = useState<number | null>(
    job.findings[0]?.id ?? null,
  );

  const counts = useMemo(() => {
    const next: Record<ReviewFindingSeverity, number> = {
      critical: 0,
      high: 0,
      medium: 0,
      low: 0,
    };
    for (const finding of job.findings) {
      next[finding.severity] += 1;
    }
    return next;
  }, [job.findings]);

  const filtered = useMemo(() => {
    return [...job.findings]
      .filter((finding) => severity === "all" || finding.severity === severity)
      .sort((left, right) => {
        const bySeverity =
          SEVERITY_ORDER[left.severity] - SEVERITY_ORDER[right.severity];
        return bySeverity !== 0 ? bySeverity : left.id - right.id;
      });
  }, [job.findings, severity]);

  const selected =
    filtered.find((finding) => finding.id === selectedId) ?? filtered[0] ?? null;
  const uiStatus = toJobUiStatus(job.status);

  if (job.status === "pending" || job.status === "processing") {
    return (
      <InlineStatus>Review is still running. Findings appear when this job finishes.</InlineStatus>
    );
  }

  if (job.status === "failed") {
    return (
      <InlineStatus tone="danger">
        {job.error_message?.trim() || "Review job failed."}
      </InlineStatus>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-[#3f3f46] bg-[#18181b] px-4 py-3">
        <div className="flex flex-wrap items-center gap-2">
          <SeverityCountChip severity="critical" count={counts.critical} />
          <SeverityCountChip severity="high" count={counts.high} />
          <SeverityCountChip severity="medium" count={counts.medium} />
          <SeverityCountChip severity="low" count={counts.low} />
          {job.findings.length === 0 ? (
            <span className="text-sm text-[#a1a1aa]">No findings</span>
          ) : null}
        </div>
        <p className="text-sm text-[#a1a1aa]">
          Last
          <span className="mx-1.5 text-[#3f3f46]">·</span>
          <span className="text-[#fafafa]">
            {uiStatus === "success" ? "Success" : uiStatus}
          </span>
          <span className="mx-1.5 text-[#3f3f46]">·</span>
          {formatRelativeTime(job.updated_at)}
        </p>
      </div>

      {job.findings.length === 0 ? (
        <InlineStatus>This review completed without findings.</InlineStatus>
      ) : (
        <div className="grid min-h-[420px] gap-4 lg:grid-cols-[minmax(240px,320px)_1fr]">
          <section className="flex flex-col overflow-hidden rounded-xl border border-[#3f3f46] bg-[#18181b]">
            <div className="flex items-center justify-between gap-3 border-b border-[#27272a] px-3 py-2.5">
              <h2 className="text-sm font-medium">Findings</h2>
              <select
                className="h-8 rounded-md border border-[#3f3f46] bg-[#09090b] px-2 text-xs text-[#fafafa] outline-none"
                value={severity}
                onChange={(event) => {
                  setSeverity(event.target.value as ReviewFindingSeverity | "all");
                }}
              >
                {SEVERITY_FILTERS.map((value) => (
                  <option key={value} value={value}>
                    {value === "all" ? "All" : value.charAt(0).toUpperCase() + value.slice(1)}
                  </option>
                ))}
              </select>
            </div>
            <ul className="flex-1 overflow-y-auto">
              {filtered.map((finding) => (
                <li key={finding.id}>
                  <button
                    type="button"
                    onClick={() => setSelectedId(finding.id)}
                    className={cn(
                      "flex w-full flex-col gap-1.5 border-b border-[#27272a] px-3 py-3 text-left hover:bg-[#27272a]/50",
                      selected?.id === finding.id ? "bg-[#27272a]" : undefined,
                    )}
                  >
                    <SeverityBadge severity={finding.severity} />
                    <span className="line-clamp-2 text-sm text-[#fafafa]">
                      {finding.summary}
                    </span>
                    <span className="truncate font-mono text-[11px] text-[#71717a]">
                      {findingLocationLabel(finding)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          </section>

          <FindingDetail
            finding={selected}
            files={files}
            jobId={job.id}
            repositoryId={repositoryId}
            pullRequestId={pullRequestId}
          />
        </div>
      )}
    </div>
  );
}

function FindingDetail({
  finding,
  files,
  jobId,
  repositoryId,
  pullRequestId,
}: {
  finding: ReviewFinding | null;
  files: PullRequestFile[];
  jobId: number;
  repositoryId: number;
  pullRequestId: number;
}) {
  if (!finding) {
    return (
      <section className="rounded-xl border border-[#3f3f46] bg-[#18181b] p-6">
        <InlineStatus>Select a finding.</InlineStatus>
      </section>
    );
  }

  const href = findingFileHref(
    repositoryId,
    pullRequestId,
    files,
    finding,
    jobId,
  );
  const file = resolveFindingFile(files, finding);

  return (
    <section className="flex flex-col gap-4 rounded-xl border border-[#3f3f46] bg-[#18181b] p-5">
      <div className="flex flex-wrap items-center gap-2">
        <SeverityBadge severity={finding.severity} />
      </div>
      <h3 className="text-lg font-medium text-[#fafafa]">{finding.summary}</h3>
      {href ? (
        <Link
          href={href}
          className="font-mono text-sm text-[#67e8f9] hover:underline"
        >
          {findingLocationLabel(finding)}
        </Link>
      ) : (
        <p className="font-mono text-sm text-[#a1a1aa]">
          {findingLocationLabel(finding)}
        </p>
      )}

      {finding.suggestion ? (
        <div className="rounded-lg border border-[#3f3f46] bg-[#27272a] px-4 py-3">
          <p className="mb-1 text-[11px] font-medium tracking-[0.12em] text-[#67e8f9]">
            SUGGESTION
          </p>
          <p className="text-sm leading-6 text-[#e4e4e7]">{finding.suggestion}</p>
        </div>
      ) : null}

      {file && finding.start_line != null ? (
        <FindingSnippet
          pullRequestId={pullRequestId}
          fileId={file.id}
          startLine={finding.start_line}
          endLine={finding.end_line ?? finding.start_line}
        />
      ) : null}
    </section>
  );
}

function FindingSnippet({
  pullRequestId,
  fileId,
  startLine,
  endLine,
}: {
  pullRequestId: number;
  fileId: number;
  startLine: number;
  endLine: number;
}) {
  const fileQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId, "files", fileId],
    queryFn: () => getPullRequestFile(pullRequestId, fileId),
  });

  const lines = snippetAround(fileQuery.data?.patch ?? null, startLine, endLine, 2);
  if (fileQuery.isLoading) {
    return <InlineStatus>Loading snippet...</InlineStatus>;
  }
  if (lines.length === 0) {
    return null;
  }

  return (
    <pre className="overflow-x-auto rounded-lg border border-[#3f3f46] bg-[#09090b] font-mono text-xs leading-6">
      <code>
        {lines.map((line, index) => (
          <div
            key={`${index}-${line.kind}`}
            className={cn(
              "grid grid-cols-[3.5rem_1fr]",
              line.kind === "add" && "bg-[#14532d]/50 text-[#86efac]",
              line.kind === "del" && "bg-[#7f1d1d]/45 text-[#fca5a5]",
              line.kind === "ctx" && "text-[#a1a1aa]",
            )}
          >
            <span className="select-none px-2 text-right text-[#52525b]">
              {line.newLine ?? line.oldLine ?? ""}
            </span>
            <span className="whitespace-pre px-3">
              {line.text.length === 0 ? " " : line.text}
            </span>
          </div>
        ))}
      </code>
    </pre>
  );
}
