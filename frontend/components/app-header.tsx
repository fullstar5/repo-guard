"use client";

import Link from "next/link";
import { useQueryClient } from "@tanstack/react-query";

import { Button } from "@/components/ui/button";
import { logout, type AuthUser } from "@/lib/api";

export function AppHeader({ user }: { user: AuthUser }) {
  const queryClient = useQueryClient();

  async function handleLogout() {
    try {
      await logout();
    } finally {
      queryClient.setQueryData(["auth", "me"], undefined);
      await queryClient.resetQueries({ queryKey: ["auth", "me"] });
    }
  }

  return (
    <header className="flex items-center justify-between">
      <div>
        <Link href="/" className="text-2xl font-semibold">
          CodeGuard AI
        </Link>
        <p className="text-sm text-zinc-600">
          Signed in as {user.github_login}
          {user.email ? ` · ${user.email}` : ""}
        </p>
      </div>
      <Button variant="outline" onClick={handleLogout}>
        Log out
      </Button>
    </header>
  );
}