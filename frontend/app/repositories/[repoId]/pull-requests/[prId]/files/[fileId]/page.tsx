"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppHeader } from "@/components/app-header";
import { DiffView, findingsToHighlights } from "@/components/diff-view";
import { SeverityBadge } from "@/components/review-findings";
import { Button } from "@/components/ui/button";
import {
  getGitHubLoginUrl,
  getPullRequest,
  getPullRequestFile,
  listReviewJobs,
} from "@/lib/api";
import { authMeQueryOptions, isInitialAuthPending } from "@/lib/auth-session";
import {
  findingLocationLabel,
  findingsForFile,
  pickSelectedReviewJob,
} from "@/lib/review-findings";

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

  const selectedJob = pickSelectedReviewJob(jobsQuery.data ?? [], jobIdParam);
  const selectedJobNotFound =
    jobIdParam != null && jobsQuery.isSuccess && selectedJob == null;

  const file = fileQuery.data;
  const fileFindings =
    selectedJob && file ? findingsForFile(selectedJob.findings, file) : [];

  useEffect(() => {
    if (!fileQuery.data || selectedJobNotFound) {
      return;
    }
    const match = window.location.hash.match(/^#L(\d+)/);
    if (!match) {
      return;
    }
    document.getElementById(`L${match[1]}`)?.scrollIntoView({
      block: "center",
    });
  }, [fileQuery.data, fileFindings.length, selectedJobNotFound]);

  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

  if (isInitialAuthPending(meQuery)) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-zinc-500">Loading session...</p>
      </main>
    );
  }

  if (unauthorized || meQuery.isError || !meQuery.data) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <Button asChild>
          <a href={getGitHubLoginUrl()}>Continue with GitHub</a>
        </Button>
      </main>
    );
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-8">
      <AppHeader user={meQuery.data} />

      <div>
        <Link
          href={`/repositories/${repositoryId}/pull-requests/${pullRequestId}${
            selectedJob ? `?jobId=${selectedJob.id}` : ""
          }`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← Changed files
        </Link>
      </div>

      <section>
        <h2 className="text-lg font-medium">
          {file?.filename ?? "Loading file..."}
        </h2>
        {file && (
          <p className="text-sm text-zinc-500">
            {file.status}
            {" · "}
            <span className="text-emerald-600">+{file.additions}</span>
            {" / "}
            <span className="text-red-600">-{file.deletions}</span>
            {prQuery.data && (
              <>
                {" · "}
                {prQuery.data.head_branch} → {prQuery.data.base_branch}
              </>
            )}
            {selectedJob && (
              <>
                {" · "}
                job #{selectedJob.id}
              </>
            )}
          </p>
        )}
        {file?.previous_filename && (
          <p className="text-xs text-zinc-500">
            renamed from {file.previous_filename}
          </p>
        )}
      </section>

      {selectedJobNotFound && (
        <p className="text-sm text-red-600">
          Review job #{jobIdParam} was not found for this pull request.
        </p>
      )}

      {selectedJob && fileFindings.length > 0 && (
        <section className="rounded-xl border bg-white p-4">
          <h3 className="mb-3 text-sm font-medium">
            Findings in this file ({fileFindings.length})
          </h3>
          <ul className="flex flex-col gap-2">
            {fileFindings.map((finding) => (
              <li key={finding.id} className="flex items-start gap-2 text-sm">
                <SeverityBadge severity={finding.severity} />
                {finding.start_line != null ? (
                  <a href={`#L${finding.start_line}`} className="hover:underline">
                    {findingLocationLabel(finding)}
                    {": "}
                    {finding.summary}
                  </a>
                ) : (
                  <span>
                    {findingLocationLabel(finding)}
                    {": "}
                    {finding.summary}
                  </span>
                )}
              </li>
            ))}
          </ul>
        </section>
      )}

      {fileQuery.isLoading ? (
        <p className="text-sm text-zinc-500">Loading diff...</p>
      ) : fileQuery.isError ? (
        <p className="text-sm text-red-600">Failed to load file diff.</p>
      ) : (
        <DiffView
          patch={file?.patch ?? null}
          highlights={selectedJob ? findingsToHighlights(fileFindings) : []}
        />
      )}
    </main>
  );
}
