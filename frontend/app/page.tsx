"use client";

import Link from "next/link";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppHeader } from "@/components/app-header";
import { LandingPage } from "@/components/landing/landing-page";
import { Button } from "@/components/ui/button";
import { isInitialAuthPending, authMeQueryOptions } from "@/lib/auth-session";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  getGitHubLoginUrl,
  listRepositories,
  syncRepositories,
} from "@/lib/api";

export default function HomePage() {
  const queryClient = useQueryClient();
  const meQuery = useQuery(authMeQueryOptions);

  const reposQuery = useQuery({
    queryKey: ["repositories"],
    queryFn: listRepositories,
    enabled: meQuery.isSuccess,
  });

  const syncMutation = useMutation({
    mutationFn: syncRepositories,
    onSuccess: (items) => {
      queryClient.setQueryData(["repositories"], items);
    },
  });

  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

  if (isInitialAuthPending(meQuery)) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[#09090b]">
        <p className="text-sm text-[#a1a1aa]">Loading session...</p>
      </main>
    );
  }

  if (unauthorized || meQuery.isError || !meQuery.data) {
    return <LandingPage loginUrl={getGitHubLoginUrl()} />;
  }

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-5xl flex-col gap-6 p-8">
      <AppHeader user={meQuery.data} />

      <section className="flex items-center justify-between">
        <div>
          <h2 className="text-lg font-medium">Repositories</h2>
          <p className="text-sm text-zinc-500">
            Synced from GitHub. Refresh the page will not call GitHub again.
          </p>
        </div>
        <Button
          onClick={() => syncMutation.mutate()}
          disabled={syncMutation.isPending}
        >
          {syncMutation.isPending ? "Syncing..." : "Sync repositories"}
        </Button>
      </section>

      {reposQuery.isLoading ? (
        <p className="text-sm text-zinc-500">Loading repositories...</p>
      ) : reposQuery.isError ? (
        <p className="text-sm text-red-600">Failed to load repositories.</p>
      ) : reposQuery.data?.length === 0 ? (
        <p className="text-sm text-zinc-500">
          No repositories yet. Click Sync repositories.
        </p>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Repository</TableHead>
              <TableHead>Visibility</TableHead>
              <TableHead>Default branch</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {reposQuery.data?.map((repo) => (
              <TableRow key={repo.id}>
                <TableCell>
                  <Link
                    href={`/repositories/${repo.id}`}
                    className="font-medium hover:underline"
                  >
                    {repo.full_name}
                  </Link>
                </TableCell>
                <TableCell>{repo.private ? "Private" : "Public"}</TableCell>
                <TableCell>{repo.default_branch ?? "-"}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </main>
  );
}