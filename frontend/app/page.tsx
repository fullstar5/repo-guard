"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { Button } from "@/components/ui/button";
import { getCurrentUser, getGitHubLoginUrl, logout } from "@/lib/api";

export default function HomePage() {
  const queryClient = useQueryClient();
  const meQuery = useQuery({
    queryKey: ["auth", "me"],
    queryFn: getCurrentUser,
  });

  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

  async function handleLogout() {
    try {
      await logout();
    } finally {
      queryClient.setQueryData(["auth", "me"], undefined);
      await queryClient.resetQueries({ queryKey: ["auth", "me"] });
    }
  }

  if (meQuery.isLoading) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-zinc-500">Loading session...</p>
      </main>
    );
  }

  if (unauthorized || meQuery.isError) {
    return (
      <main className="flex min-h-screen items-center justify-center">
        <div className="flex w-full max-w-md flex-col gap-4 rounded-xl border p-8">
          <h1 className="text-2xl font-semibold">CodeGuard AI</h1>
          <p className="text-sm text-zinc-600">
            Sign in with GitHub to review pull requests.
          </p>
          <Button asChild>
            <a href={getGitHubLoginUrl()}>Continue with GitHub</a>
          </Button>
        </div>
      </main>
    );
  }

  const user = meQuery.data;

  return (
    <main className="mx-auto flex min-h-screen w-full max-w-3xl flex-col gap-6 p-8">
      <header className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold">CodeGuard AI</h1>
          <p className="text-sm text-zinc-600">
            Signed in as {user?.github_login}
            {user?.email ? ` · ${user.email}` : ""}
          </p>
        </div>
        <Button variant="outline" onClick={handleLogout}>
          Log out
        </Button>
      </header>
      <p className="text-sm text-zinc-500">
        Auth is working. Repository and PR views come in Step 8B.
      </p>
    </main>
  );
}