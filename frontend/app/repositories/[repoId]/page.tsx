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
  getCurrentUser,
  getGitHubLoginUrl,
  listPullRequests,
  syncPullRequests,
} from "@/lib/api";

export default function RepositoryPullRequestsPage() {
  const params = useParams<{ repoId: string }>();
  const repositoryId = Number(params.repoId);
  const queryClient = useQueryClient();

  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
  });

  const prsQuery = useQuery({
    queryKey: ["repositories", repositoryId, "pull-requests"],
    queryFn: () => listPullRequests(repositoryId),
    enabled: meQuery.isSuccess && Number.isFinite(repositoryId),
  });

  const syncMutation = useMutation({
    mutationFn: () => syncPullRequests(repositoryId),
    onSuccess: (items) => {
      queryClient.setQueryData(
        ["repositories", repositoryId, "pull-requests"],
        items,
      );
    },
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

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-8">
      <AppHeader user={meQuery.data} />

      <div>
        <Link href="/" className="text-sm text-zinc-500 hover:underline">
          ← Repositories
        </Link>
      </div>

      <section className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium">Pull requests</h2>
          <p className="text-sm text-zinc-500">
            Sync this repository to refresh GitHub PR data.
          </p>
        </div>
        <Button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
        >
          {syncMutation.isPending ? "Syncing..." : "Sync pull requests"}
        </Button>
      </section>

      {prsQuery.isLoading ? (
        <p className="text-sm text-zinc-500">Loading pull requests...</p>
      ) : prsQuery.isError ? (
        <p className="text-sm text-red-600">Failed to load pull requests.</p>
      ) : prsQuery.data?.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No pull requests yet. Click Sync pull requests.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>PR</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>State</TableHead>
              <TableHead>Author</TableHead>
              <TableHead>Branches</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {prsQuery.data?.map((pr) => (
              <TableRow key={pr.id}>
                <TableCell>
                  <a
                    href={pr.html_url}
                    target="_blank"
                    rel="noreferrer"
                    className="hover:underline"
                  >
                    #{pr.number}
                  </a>
                </TableCell>
                <TableCell>{pr.title}</TableCell>
                <TableCell>{pr.is_draft ? "draft" : pr.state}</TableCell>
                <TableCell>{pr.author_login ?? "-"}</TableCell>
                <TableCell>
                  {pr.head_branch} → {pr.base_branch}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </main>
  );
}