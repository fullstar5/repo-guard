"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppShell } from "@/components/app-shell";
import { LandingPage } from "@/components/landing/landing-page";
import { authMeQueryOptions, isInitialAuthPending } from "@/lib/auth-session";
import { getGitHubLoginUrl } from "@/lib/api";

export function LoadingSession() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-[#09090b]">
      <p className="text-sm text-[#a1a1aa]">Loading session...</p>
    </main>
  );
}

export function AuthGate({ children }: { children: ReactNode }) {
  const meQuery = useQuery(authMeQueryOptions);
  const unauthorized =
    meQuery.isError &&
    isAxiosError(meQuery.error) &&
    meQuery.error.response?.status === 401;

  if (isInitialAuthPending(meQuery)) {
    return <LoadingSession />;
  }

  if (unauthorized) {
    return <LandingPage loginUrl={getGitHubLoginUrl()} />;
  }

  if (meQuery.isError) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center gap-3 bg-[#09090b]">
        <p className="text-sm text-[#fca5a5]">Couldn&apos;t load your session.</p>
        <button
          type="button"
          className="text-sm text-[#67e8f9] hover:underline"
          onClick={() => {
            void meQuery.refetch();
          }}
        >
          Try again
        </button>
      </main>
    );
  }

  if (!meQuery.data) {
    return <LandingPage loginUrl={getGitHubLoginUrl()} />;
  }

  return <AppShell user={meQuery.data}>{children}</AppShell>;
}
