"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ChevronLeft, ChevronRight } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { DiffView, findingsToHighlights } from "@/components/diff-view";
import { Breadcrumbs } from "@/components/page-chrome";
import { InlineStatus } from "@/components/empty-state";
import { SeverityBadge } from "@/components/status-badges";
import { Button } from "@/components/ui/button";
import {
  getPullRequest,
  getPullRequestFile,
  listReviewJobs,
} from "@/lib/api";
import { authMeQueryOptions } from "@/lib/auth-session";
import {
  findingLocationLabel,
  findingsForFile,
  pickSelectedReviewJob,
  resolveDisplayedReviewJob,
} from "@/lib/review-findings";
import { cn } from "@/lib/utils";
import { useRepository } from "@/lib/use-repository";

export default function PullRequestFilePage() {
  const params = useParams<{ repoId: string; prId: string; fileId: string }>();
  const searchParams = useSearchParams();
  const repositoryId = Number(params.repoId);
  const pullRequestId = Number(params.prId);
  const fileId = Number(params.fileId);
  const jobIdParam = searchParams.get("jobId");
  const idsReady =
    Number.isFinite(repositoryId) &&
    Number.isFinite(pullRequestId) &&
    Number.isFinite(fileId);

  const meQuery = useQuery(authMeQueryOptions);
  const { repository } = useRepository(repositoryId);

  const prQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId],
    queryFn: () => getPullRequest(pullRequestId),
    enabled: meQuery.isSuccess && idsReady,
  });

  const fileQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId, "files", fileId],
    queryFn: () => getPullRequestFile(pullRequestId, fileId),
    enabled: meQuery.isSuccess && idsReady,
  });

  const jobsQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId, "review-jobs"],
    queryFn: () => listReviewJobs(pullRequestId),
    enabled: meQuery.isSuccess && idsReady,
  });

  const explicitJob = pickSelectedReviewJob(jobsQuery.data ?? [], jobIdParam);
  const selectedJobNotFound =
    jobIdParam != null && jobsQuery.isSuccess && explicitJob == null;
  const selectedJob = selectedJobNotFound
    ? undefined
    : resolveDisplayedReviewJob(jobsQuery.data ?? [], jobIdParam);

  const file = fileQuery.data;
  const fileFindings = useMemo(
    () => (selectedJob && file ? findingsForFile(selectedJob.findings, file) : []),
    [selectedJob, file],
  );
  const [findingCursor, setFindingCursor] = useState({
    fileId,
    jobId: selectedJob?.id ?? null,
    index: 0,
  });
  const cursorMatches =
    findingCursor.fileId === fileId &&
    findingCursor.jobId === (selectedJob?.id ?? null);
  const activeFindingIndex = cursorMatches ? findingCursor.index : 0;
  const scopedFindingIndex =
    fileFindings.length === 0
      ? 0
      : Math.min(activeFindingIndex, fileFindings.length - 1);

  useEffect(() => {
    if (!fileQuery.data || selectedJobNotFound) {
      return;
    }
    const match = window.location.hash.match(/^#L(\d+)/);
    if (match) {
      document.getElementById(`L${match[1]}`)?.scrollIntoView({
        block: "center",
      });
      return;
    }
    const finding = fileFindings[scopedFindingIndex];
    if (finding?.start_line != null) {
      document.getElementById(`L${finding.start_line}`)?.scrollIntoView({
        block: "center",
      });
    }
  }, [fileQuery.data, fileFindings, scopedFindingIndex, selectedJobNotFound]);

  const backHref = `/repositories/${repositoryId}/pull-requests/${pullRequestId}${
    selectedJob ? `?jobId=${selectedJob.id}&tab=files` : "?tab=files"
  }`;

  function goFinding(next: number) {
    if (fileFindings.length === 0) {
      return;
    }
    const index = (next + fileFindings.length) % fileFindings.length;
    setFindingCursor({
      fileId,
      jobId: selectedJob?.id ?? null,
      index,
    });
    const finding = fileFindings[index];
    if (finding.start_line != null) {
      window.location.hash = `L${finding.start_line}`;
    }
  }

  return (
    <AuthGate>
      <Breadcrumbs
        items={[
          { label: "Repositories", href: "/" },
          {
            label: repository?.full_name ?? `Repository ${repositoryId}`,
            href: `/repositories/${repositoryId}`,
          },
          {
            label: prQuery.data ? `PR #${prQuery.data.number}` : `PR ${pullRequestId}`,
            href: backHref,
          },
          { label: file?.filename ?? "File" },
        ]}
      />

      <div className="sticky top-14 z-10 -mx-8 mb-6 flex flex-wrap items-center justify-between gap-3 border-y border-[#27272a] bg-[#09090b] px-8 py-3">
        <div className="min-w-0">
          <p className="truncate font-mono text-sm text-[#fafafa]">
            {file?.filename ?? "Loading file..."}
          </p>
          {file ? (
            <p className="mt-1 font-mono text-xs tabular-nums">
              <span className="text-[#4ade80]">+{file.additions}</span>{" "}
              <span className="text-[#f87171]">-{file.deletions}</span>
            </p>
          ) : null}
        </div>
        <div className="flex items-center gap-2">
          {fileFindings.length > 0 ? (
            <div className="flex items-center gap-1">
              <span className="px-1 text-xs tabular-nums text-[#a1a1aa]">
                {scopedFindingIndex + 1} / {fileFindings.length}
              </span>
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() => goFinding(scopedFindingIndex - 1)}
                aria-label="Previous finding"
              >
                <ChevronLeft />
              </Button>
              <Button
                variant="outline"
                size="icon-sm"
                onClick={() => goFinding(scopedFindingIndex + 1)}
                aria-label="Next finding"
              >
                <ChevronRight />
              </Button>
            </div>
          ) : null}
          <Button variant="outline" asChild>
            <Link href={backHref}>Back to PR</Link>
          </Button>
        </div>
      </div>

      {selectedJobNotFound ? (
        <InlineStatus tone="danger">
          Review job #{jobIdParam} was not found for this pull request.
        </InlineStatus>
      ) : null}

      <div
        className={cn(
          "grid gap-4",
          fileFindings.length > 0 ? "lg:grid-cols-[minmax(220px,280px)_1fr]" : undefined,
        )}
      >
        {selectedJob && fileFindings.length > 0 ? (
          <section className="overflow-hidden rounded-xl border border-[#3f3f46] bg-[#18181b]">
            <h2 className="border-b border-[#27272a] px-3 py-2.5 text-sm font-medium">
              Findings
            </h2>
            <ul>
              {fileFindings.map((finding, index) => (
                <li key={finding.id}>
                  <a
                    href={finding.start_line != null ? `#L${finding.start_line}` : undefined}
                    onClick={() =>
                      setFindingCursor({
                        fileId,
                        jobId: selectedJob?.id ?? null,
                        index,
                      })
                    }
                    className={cn(
                      "flex flex-col items-start gap-1.5 border-b border-[#27272a] px-3 py-3 hover:bg-[#27272a]/50",
                      index === scopedFindingIndex ? "bg-[#27272a] shadow-[inset_2px_0_0_#22d3ee]" : undefined,
                    )}
                  >
                    <SeverityBadge severity={finding.severity} />
                    <span className="line-clamp-2 text-sm text-[#fafafa]">
                      {finding.summary}
                    </span>
                    <span className="font-mono text-[11px] text-[#71717a]">
                      {findingLocationLabel(finding)}
                    </span>
                  </a>
                </li>
              ))}
            </ul>
          </section>
        ) : null}

        <div className="min-w-0">
          {fileQuery.isLoading ? (
            <InlineStatus>Loading diff...</InlineStatus>
          ) : fileQuery.isError ? (
            <InlineStatus tone="danger">Failed to load file diff.</InlineStatus>
          ) : (
            <DiffView
              patch={file?.patch ?? null}
              highlights={selectedJob ? findingsToHighlights(fileFindings) : []}
            />
          )}
        </div>
      </div>
    </AuthGate>
  );
}
