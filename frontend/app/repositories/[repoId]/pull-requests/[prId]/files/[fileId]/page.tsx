"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppHeader } from "@/components/app-header";
import { DiffView } from "@/components/diff-view";
import { Button } from "@/components/ui/button";
import {
  getCurrentUser,
  getGitHubLoginUrl,
  getPullRequest,
  getPullRequestFile,
} from "@/lib/api";

export default function PullRequestFilePage() {
  const params = useParams<{ repoId: string; prId: string; fileId: string }>();
  const repositoryId = Number(params.repoId);
  const pullRequestId = Number(params.prId);
  const fileId = Number(params.fileId);
  const idsReady =
    Number.isFinite(repositoryId) &&
    Number.isFinite(pullRequestId) &&
    Number.isFinite(fileId);

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
  });

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

  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

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

  const file = fileQuery.data;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-8">
      <AppHeader user={meQuery.data} />

      <div>
        <Link
          href={`/repositories/${repositoryId}/pull-requests/${pullRequestId}`}
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
          </p>
        )}
        {file?.previous_filename && (
          <p className="text-xs text-zinc-500">
            renamed from {file.previous_filename}
          </p>
        )}
      </section>

      {fileQuery.isLoading ? (
        <p className="text-sm text-zinc-500">Loading diff...</p>
      ) : fileQuery.isError ? (
        <p className="text-sm text-red-600">Failed to load file diff.</p>
      ) : (
        <DiffView patch={file?.patch ?? null} />
      )}
    </main>
  );
}
