"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppHeader } from "@/components/app-header";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  createReviewJob,
  getCurrentUser,
  getGitHubLoginUrl,
  getPullRequest,
  listPullRequestFiles,
  listReviewJobs,
  syncPullRequestFiles,
  type ReviewJob,
} from "@/lib/api";

const ACTIVE_STATUSES = new Set(["pending", "processing"]);

function isActiveJob(job: ReviewJob): boolean {
  return ACTIVE_STATUSES.has(job.status);
}

export default function PullRequestReviewPage() {
  const params = useParams<{ repoId: string; prId: string }>();
  const repositoryId = Number(params.repoId);
  const pullRequestId = Number(params.prId);
  const queryClient = useQueryClient();
  const idsReady = Number.isFinite(repositoryId) && Number.isFinite(pullRequestId);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
  });

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
      return jobs.some(isActiveJob) ? 2000 : false;
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
    },
  });

  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

  const hasActiveJob = (jobsQuery.data ?? []).some(isActiveJob);
  const fileCount = filesQuery.data?.length ?? 0;

  if (meQuery.isLoading) {
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
          href={`/repositories/${repositoryId}`}
          className="text-sm text-zinc-500 hover:underline"
        >
          ← Pull requests
        </Link>
      </div>

      <section className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-lg font-medium">
            {prQuery.data
              ? `#${prQuery.data.number} ${prQuery.data.title}`
              : `Pull request #${pullRequestId}`}
          </h2>
          {prQuery.data && (
            <p className="text-sm text-zinc-500">
              {prQuery.data.head_branch} → {prQuery.data.base_branch}
              {" · "}
              <a
                href={prQuery.data.html_url}
                target="_blank"
                rel="noreferrer"
                className="hover:underline"
              >
                Open on GitHub
              </a>
            </p>
          )}
        </div>
        <div className="flex gap-2">
          <Button
            variant="outline"
            onClick={() => syncFilesMutation.mutate()}
            disabled={syncFilesMutation.isPending}
          >
            {syncFilesMutation.isPending ? "Syncing files..." : "Sync files"}
          </Button>
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

      {fileCount === 0 && (
        <p className="text-sm text-zinc-500">
          No files synced yet. Sync files before running a review.
        </p>
      )}

      {createJobMutation.isError && (
        <p className="text-sm text-red-600">Failed to enqueue review job.</p>
      )}

      <section>
        <h3 className="mb-3 text-base font-medium">Review jobs</h3>
        {jobsQuery.isLoading ? (
          <p className="text-sm text-zinc-500">Loading review jobs...</p>
        ) : jobsQuery.isError ? (
          <p className="text-sm text-red-600">Failed to load review jobs.</p>
        ) : jobsQuery.data?.length === 0 ? (
          <p className="text-sm text-zinc-500">
            No review jobs yet. Sync files, then run AI review.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Files / chunks</TableHead>
                <TableHead>Error</TableHead>
                <TableHead>Updated</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {jobsQuery.data?.map((job) => (
                <TableRow key={job.id}>
                  <TableCell>{job.id}</TableCell>
                  <TableCell>{job.status}</TableCell>
                  <TableCell>
                    {job.total_files} / {job.total_chunks}
                  </TableCell>
                  <TableCell className="max-w-xs truncate text-red-600">
                    {job.error_message ?? "-"}
                  </TableCell>
                  <TableCell>
                    {new Date(job.updated_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </section>
    </main>
  );
}