"use client";

import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { useParams, usePathname, useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { ChangedFilesTable } from "@/components/changed-files-table";
import { EmptyState } from "@/components/empty-state";
import { FilterEmpty, PanelSkeleton, QueryError, TableSkeleton } from "@/components/feedback";
import { HistoricalJobBanner } from "@/components/historical-job-banner";
import { Breadcrumbs } from "@/components/page-chrome";
import { ReviewJobsTable } from "@/components/review-jobs-table";
import { ReviewWorkspace } from "@/components/review-workspace";
import { PullRequestStateBadge } from "@/components/status-badges";
import { SyncButton } from "@/components/sync-button";
import { useToast } from "@/components/toast";
import { Button } from "@/components/ui/button";
import {
  isHistoricalJobPin,
  latestReviewJob,
  pickSelectedReviewJob,
  resolveDisplayedReviewJob,
} from "@/lib/review-findings";
import { authMeQueryOptions } from "@/lib/auth-session";
import { isActiveJob } from "@/lib/job-status";
import { reviewModelLabel } from "@/lib/review-models";
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
  listReviewModels,
  syncPullRequestFiles,
} from "@/lib/api";

function TabPanel({
  id,
  labelledBy,
  active,
  children,
}: {
  id: string;
  labelledBy: string;
  active: boolean;
  children: ReactNode;
}) {
  return (
    <div
      role="tabpanel"
      id={id}
      aria-labelledby={labelledBy}
      hidden={!active}
      {...(!active ? { inert: true } : {})}
    >
      {children}
    </div>
  );
}

export default function PullRequestReviewPage() {
  const params = useParams<{ repoId: string; prId: string }>();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const router = useRouter();
  const toast = useToast();
  const repositoryId = Number(params.repoId);
  const pullRequestId = Number(params.prId);
  const queryClient = useQueryClient();
  const idsReady = Number.isFinite(repositoryId) && Number.isFinite(pullRequestId);
  const jobIdParam = searchParams.get("jobId");
  const historicalPin = isHistoricalJobPin(jobIdParam);
  const requestedTab = parsePrTab(searchParams.get("tab"));
  const [lastOpenedJobId, setLastOpenedJobId] = useState<number | undefined>();
  const [modelName, setModelName] = useState("openrouter/free");

  const meQuery = useQuery(authMeQueryOptions);
  const { repository } = useRepository(repositoryId);

  const modelsQuery = useQuery({
    queryKey: ["review-models"],
    queryFn: listReviewModels,
    enabled: meQuery.isSuccess,
  });

  useEffect(() => {
    const models = modelsQuery.data?.models ?? [];
    if (models.length === 0 || models.includes(modelName)) {
      return;
    }
    setModelName(modelsQuery.data?.default_model ?? models[0]);
  }, [modelsQuery.data, modelName]);

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
      toast({ tone: "success", message: "Files updated." });
    },
    onError: () => {
      toast({ tone: "danger", message: "Couldn't sync files." });
    },
  });

  const createJobMutation = useMutation({
    mutationFn: () => createReviewJob(pullRequestId, modelName),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: ["pull-requests", pullRequestId, "review-jobs"],
      });
      setLastOpenedJobId(undefined);
      if (historicalPin) {
        const next = prClearJobPinHref(searchParams);
        router.replace(next ? `${pathname}${next}` : pathname, { scroll: false });
      }
      toast({ tone: "success", message: "Review queued." });
    },
    onError: () => {
      toast({ tone: "danger", message: "Couldn't start AI review." });
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
  const modelOptions = modelsQuery.data?.models ?? ["openrouter/free"];
  const runDisabled =
    createJobMutation.isPending || hasActiveJob || fileCount === 0;
  const runTitle =
    fileCount === 0
      ? "Sync files before running a review"
      : hasActiveJob
        ? "A review is already running"
        : undefined;

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
          <h1
            className="truncate text-2xl font-semibold tracking-tight text-[#fafafa]"
            title={prQuery.data?.title}
          >
            {prQuery.data?.title ?? "Pull request"}
          </h1>
          {prQuery.data ? (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <PullRequestStateBadge
                state={prQuery.data.state}
                isDraft={prQuery.data.is_draft}
              />
              <span
                className="rounded-md bg-[#18181b] px-2 py-0.5 font-mono text-xs text-[#d4d4d8] ring-1 ring-[#3f3f46]"
                title={prQuery.data.base_branch}
              >
                {prQuery.data.base_branch}
              </span>
              <span className="text-[#3f3f46]">→</span>
              <span
                className="rounded-md bg-[#18181b] px-2 py-0.5 font-mono text-xs text-[#d4d4d8] ring-1 ring-[#3f3f46]"
                title={prQuery.data.head_branch}
              >
                {prQuery.data.head_branch}
              </span>
            </div>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex items-center gap-2 text-sm text-[#a1a1aa]">
            <span className="sr-only">Review model</span>
            <select
              value={modelOptions.includes(modelName) ? modelName : modelOptions[0]}
              onChange={(event) => setModelName(event.target.value)}
              disabled={runDisabled}
              aria-label="Review model"
              className="h-9 max-w-[14rem] rounded-md border border-[#3f3f46] bg-[#18181b] px-2 text-sm text-[#fafafa] outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 disabled:cursor-not-allowed disabled:opacity-40"
            >
              {modelOptions.map((model) => (
                <option key={model} value={model}>
                  {reviewModelLabel(model)}
                </option>
              ))}
            </select>
          </label>
          {prQuery.data ? (
            <Button variant="outline" asChild>
              <a href={prQuery.data.html_url} target="_blank" rel="noreferrer">
                Open on GitHub
              </a>
            </Button>
          ) : null}
          <Button
            onClick={() => createJobMutation.mutate()}
            disabled={runDisabled}
            title={runTitle}
            aria-label={
              hasActiveJob
                ? "Review running"
                : fileCount === 0
                  ? "Run AI review, sync files first"
                  : "Run AI review"
            }
          >
            {hasActiveJob ? "Review running…" : "Run AI review"}
          </Button>
        </div>
      </section>

      <div
        role="tablist"
        aria-label="Pull request sections"
        className="mb-6 inline-flex rounded-lg border border-[#3f3f46] bg-[#18181b] p-1"
      >
        {(["review", "files", "jobs"] as const).map((item) => (
          <Link
            key={item}
            id={`pr-tab-${item}`}
            role="tab"
            aria-selected={tab === item}
            aria-controls={`pr-panel-${item}`}
            href={prTabHref(searchParams, item)}
            scroll={false}
            className={cn(
              "rounded-md px-3 py-1.5 text-sm capitalize focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none",
              tab === item
                ? "bg-[#27272a] text-[#fafafa]"
                : "text-[#a1a1aa] hover:text-[#fafafa]",
            )}
          >
            {item}
          </Link>
        ))}
      </div>

      <TabPanel id="pr-panel-review" labelledBy="pr-tab-review" active={tab === "review"}>
          {jobsQuery.isLoading ? (
            <PanelSkeleton />
          ) : jobsQuery.isError ? (
            <QueryError
              message="Failed to load review jobs."
              onRetry={() => void jobsQuery.refetch()}
            />
          ) : selectedJobNotFound ? (
            <>
              <HistoricalJobBanner
                jobId={jobIdParam ?? ""}
                latestHref={latestReviewHref}
                onBackToLatest={() => setLastOpenedJobId(latestJob?.id)}
              />
              <QueryError message={`Review job #${jobIdParam} was not found for this pull request.`} />
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
                  : "Choose a model, then run an AI review."
              }
            />
          )}
        </TabPanel>

      <TabPanel id="pr-panel-files" labelledBy="pr-tab-files" active={tab === "files"}>
          <div className="flex flex-col gap-4">
            {filesQuery.isLoading ? (
              <TableSkeleton columns={3} rows={5} />
            ) : filesQuery.isError ? (
              <QueryError
                message="Failed to load files."
                onRetry={() => void filesQuery.refetch()}
              />
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
                    aria-label={
                      syncFilesMutation.isPending ? "Syncing files" : "Sync files"
                    }
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
        </TabPanel>

      <TabPanel id="pr-panel-jobs" labelledBy="pr-tab-jobs" active={tab === "jobs"}>
          {jobsQuery.isLoading ? (
            <TableSkeleton columns={6} rows={4} />
          ) : jobsQuery.isError ? (
            <QueryError
              message="Failed to load review jobs."
              onRetry={() => void jobsQuery.refetch()}
            />
          ) : jobs.length === 0 ? (
            <FilterEmpty
              title="No review jobs yet"
              hint="Sync files, then run an AI review."
            />
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
          )}
        </TabPanel>
    </AuthGate>
  );
}
