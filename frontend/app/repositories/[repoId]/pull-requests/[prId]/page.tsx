"use client";

import Link from "next/link";
import { useState } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { ChangedFilesTable } from "@/components/changed-files-table";
import { EmptyState, InlineStatus } from "@/components/empty-state";
import { HistoricalJobBanner } from "@/components/historical-job-banner";
import { Breadcrumbs } from "@/components/page-chrome";
import { ReviewJobsTable } from "@/components/review-jobs-table";
import { ReviewWorkspace } from "@/components/review-workspace";
import { PullRequestStateBadge } from "@/components/status-badges";
import { SyncButton } from "@/components/sync-button";
import { Button } from "@/components/ui/button";
import {
  isHistoricalJobPin,
  latestReviewJob,
  pickSelectedReviewJob,
  resolveDisplayedReviewJob,
} from "@/lib/review-findings";
import { authMeQueryOptions } from "@/lib/auth-session";
import { isActiveJob } from "@/lib/job-status";
import {
  parsePrTab,
  prClearJobPinHref,
  prJobHref,
  prLatestReviewHref,
  prTabHref,
} from "@/lib/pr-query";
import { cn } from "@/lib/utils";
import { useRepository } from "@/lib/use-repository";
import {
  createReviewJob,
  getPullRequest,
  listPullRequestFiles,
  listReviewJobs,
  syncPullRequestFiles,
} from "@/lib/api";

export default function PullRequestReviewPage() {
  const params = useParams<{ repoId: string; prId: string }>();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const repositoryId = Number(params.repoId);
  const pullRequestId = Number(params.prId);
  const queryClient = useQueryClient();
  const idsReady = Number.isFinite(repositoryId) && Number.isFinite(pullRequestId);
  const jobIdParam = searchParams.get("jobId");
  const historicalPin = isHistoricalJobPin(jobIdParam);
  const requestedTab = parsePrTab(searchParams.get("tab"));
  const [lastOpenedJobId, setLastOpenedJobId] = useState<number | undefined>();

  const meQuery = useQuery(authMeQueryOptions);
  const { repository } = useRepository(repositoryId);

  const prQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId],
    queryFn: () => getPullRequest(pullRequestId),
    enabled: meQuery.isSuccess && idsReady,
  });

  const filesQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId, "files"],
    queryFn: () => listPullRequestFiles(pullRequestId),
    enabled: meQuery.isSuccess && idsReady,
  });

  const jobsQuery = useQuery({
    queryKey: ["pull-requests", pullRequestId, "review-jobs"],
    queryFn: () => listReviewJobs(pullRequestId),
    enabled: meQuery.isSuccess && idsReady,
    refetchInterval: (query) => {
      const jobs = query.state.data ?? [];
      return jobs.some(isActiveJob) ? 60000 : false;
    },
  });

  const syncFilesMutation = useMutation({
    mutationFn: () => syncPullRequestFiles(pullRequestId),
    onSuccess: (items) => {
      queryClient.setQueryData(["pull-requests", pullRequestId, "files"], items);
    },
  });

  const createJobMutation = useMutation({
    mutationFn: () => createReviewJob(pullRequestId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pull-requests", pullRequestId, "review-jobs"],
      });
      setLastOpenedJobId(undefined);
      if (historicalPin) {
        const next = prClearJobPinHref(searchParams);
        router.replace(next ? `${pathname}${next}` : pathname, { scroll: false });
      }
    },
  });

  const jobs = jobsQuery.data ?? [];
  const hasActiveJob = jobs.some(isActiveJob);
  const fileCount = filesQuery.data?.length ?? 0;
  const explicitJob = pickSelectedReviewJob(jobs, jobIdParam);
  const latestJob = latestReviewJob(jobs);
  const selectedJob = resolveDisplayedReviewJob(jobs, jobIdParam);
  const selectedJobNotFound =
    historicalPin && jobsQuery.isSuccess && explicitJob == null;
  const hasFindings =
    selectedJob?.status === "completed" && (selectedJob.findings.length ?? 0) > 0;
  const tab = requestedTab ?? (historicalPin || hasFindings ? "review" : "files");
  const latestReviewHref = prLatestReviewHref(searchParams);
  const jobsHighlightId = explicitJob?.id ?? lastOpenedJobId ?? latestJob?.id;

  return (
    <AuthGate>
      <Breadcrumbs
        items={[
          { label: "Repositories", href: "/" },
          {
            label: repository?.full_name ?? `Repository ${repositoryId}`,
            href: `/repositories/${repositoryId}`,
          },
          { label: prQuery.data ? `PR #${prQuery.data.number}` : `PR ${pullRequestId}` },
        ]}
      />

      <section className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-[#fafafa]">
            {prQuery.data?.title ?? "Pull request"}
          </h1>
          {prQuery.data ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <PullRequestStateBadge
                state={prQuery.data.state}
                isDraft={prQuery.data.is_draft}
              />
              <span className="rounded-md bg-[#18181b] px-2 py-0.5 font-mono text-xs text-[#a1a1aa] ring-1 ring-[#3f3f46]">
                {prQuery.data.base_branch}
              </span>
              <span className="text-[#3f3f46]">→</span>
              <span className="rounded-md bg-[#18181b] px-2 py-0.5 font-mono text-xs text-[#a1a1aa] ring-1 ring-[#3f3f46]">
                {prQuery.data.head_branch}
              </span>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap gap-2">
          {prQuery.data ? (
            <Button variant="outline" asChild>
              <a href={prQuery.data.html_url} target="_blank" rel="noreferrer">
                Open on GitHub
              </a>
            </Button>
          ) : null}
          <Button
            onClick={() => createJobMutation.mutate()}
            disabled={
              createJobMutation.isPending || hasActiveJob || fileCount === 0
            }
          >
            {hasActiveJob ? "Review running..." : "Run AI review"}
          </Button>
        </div>
      </section>

      {createJobMutation.isError ? (
        <div className="mb-4">
          <InlineStatus tone="danger">Failed to enqueue review job.</InlineStatus>
        </div>
      ) : null}

      <div className="mb-6 inline-flex rounded-lg border border-[#3f3f46] bg-[#18181b] p-1">
        {(["review", "files", "jobs"] as const).map((item) => (
          <Link
            key={item}
            href={prTabHref(searchParams, item)}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm capitalize",
              tab === item
                ? "bg-[#27272a] text-[#fafafa]"
                : "text-[#a1a1aa] hover:text-[#fafafa]",
            )}
          >
            {item}
          </Link>
        ))}
      </div>

      {tab === "review" ? (
        selectedJobNotFound ? (
          <>
            <HistoricalJobBanner
              jobId={jobIdParam ?? ""}
              latestHref={latestReviewHref}
              onBackToLatest={() => setLastOpenedJobId(latestJob?.id)}
            />
            <InlineStatus tone="danger">
              Review job #{jobIdParam} was not found for this pull request.
            </InlineStatus>
          </>
        ) : selectedJob ? (
          <>
            {historicalPin ? (
              <HistoricalJobBanner
                jobId={selectedJob.id}
                updatedAt={selectedJob.updated_at}
                latestHref={latestReviewHref}
                onBackToLatest={() => setLastOpenedJobId(latestJob?.id)}
              />
            ) : null}
            <ReviewWorkspace
              key={selectedJob.id}
              job={selectedJob}
              files={filesQuery.data ?? []}
              repositoryId={repositoryId}
              pullRequestId={pullRequestId}
            />
          </>
        ) : (
          <EmptyState
            icon={<RefreshCw className="size-7 text-[#22d3ee]" aria-hidden="true" />}
            title="No review yet"
            hint={
              fileCount === 0
                ? "Sync files, then run an AI review."
                : "Run AI review with the workspace default model."
            }
          />
        )
      ) : null}

      {tab === "files" ? (
        <div className="flex flex-col gap-4">
          {filesQuery.isLoading ? (
            <InlineStatus>Loading files...</InlineStatus>
          ) : filesQuery.isError ? (
            <InlineStatus tone="danger">Failed to load files.</InlineStatus>
          ) : (filesQuery.data?.length ?? 0) === 0 ? (
            <EmptyState
              icon={<RefreshCw className="size-7 text-[#22d3ee]" aria-hidden="true" />}
              title="No files synced yet"
              hint="Sync files before running a review."
              actionLabel="Sync"
              onAction={() => syncFilesMutation.mutate()}
              actionPending={syncFilesMutation.isPending}
            />
          ) : (
            <>
              <div className="flex items-center justify-end">
                <SyncButton
                  pending={syncFilesMutation.isPending}
                  onClick={() => syncFilesMutation.mutate()}
                />
              </div>
              <ChangedFilesTable
                files={filesQuery.data ?? []}
                hrefForFile={(file) =>
                  `/repositories/${repositoryId}/pull-requests/${pullRequestId}/files/${file.id}`
                }
              />
            </>
          )}
        </div>
      ) : null}

      {tab === "jobs" ? (
        jobsQuery.isLoading ? (
          <InlineStatus>Loading review jobs...</InlineStatus>
        ) : jobsQuery.isError ? (
          <InlineStatus tone="danger">Failed to load review jobs.</InlineStatus>
        ) : jobs.length === 0 ? (
          <InlineStatus>No review jobs yet. Sync files, then run AI review.</InlineStatus>
        ) : (
          <ReviewJobsTable
            jobs={jobs}
            selectedJobId={jobsHighlightId}
            hrefForJob={(job) => prJobHref(searchParams, job.id)}
            onSelectJob={(job) => setLastOpenedJobId(job.id)}
            onRetry={() => createJobMutation.mutate()}
            retryDisabled={hasActiveJob || fileCount === 0}
            retryPending={createJobMutation.isPending}
          />
        )
      ) : null}
    </AuthGate>
  );
}
