"use client";

import type { ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { isAxiosError } from "axios";

import { AppShell } from "@/components/app-shell";
import { AppShellSkeleton } from "@/components/feedback";
import { LandingPage } from "@/components/landing/landing-page";
import { authMeQueryOptions, isInitialAuthPending } from "@/lib/auth-session";
import { getGitHubLoginUrl } from "@/lib/api";

export function LoadingSession() {
  return <AppShellSkeleton />;
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

  if (unauthorized || meQuery.isError || !meQuery.data) {
    return <LandingPage loginUrl={getGitHubLoginUrl()} />;
  }

  return <AppShell user={meQuery.data}>{children}</AppShell>;
}
