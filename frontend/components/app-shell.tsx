"use client";

import Link from "next/link";
import { type ReactNode } from "react";
import { ChevronDown, LayoutGrid, ShieldCheck } from "lucide-react";

import { logout, type AuthUser } from "@/lib/api";
import { initialsFromLogin } from "@/lib/format";
import { clearSyncListCache } from "@/lib/sync-list-cache";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export function AppShell({
  user,
  children,
}: {
  user: AuthUser;
  children: ReactNode;
}) {
  return (
    <div className="flex min-h-screen bg-[#09090b] text-[#fafafa]">
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-[#27272a] bg-[#09090b]">
        <div className="flex h-14 items-center gap-2.5 px-4">
          <ShieldCheck className="size-5 text-[#22d3ee]" strokeWidth={1.75} aria-hidden="true" />
          <span className="text-sm font-medium tracking-tight">CodeGuard AI</span>
        </div>
        <nav className="flex flex-1 flex-col px-3 py-2">
          <Link
            href="/"
            className={cn(
              "flex items-center gap-2.5 rounded-lg bg-[#18181b] px-3 py-2 text-sm font-medium text-[#fafafa]",
            )}
          >
            <LayoutGrid className="size-4 text-[#a1a1aa]" aria-hidden="true" />
            Repositories
          </Link>
        </nav>
        <div className="border-t border-[#27272a] px-4 py-3 text-sm text-[#71717a]">
          {user.github_login}
        </div>
      </aside>

      <div className="flex min-h-screen min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between overflow-visible border-b border-[#27272a] bg-[#09090b] px-6">
          <p className="text-sm text-[#a1a1aa]">
            Workspace
            <span className="mx-2 text-[#3f3f46]">·</span>
            <span className="font-medium text-[#fafafa]">{user.github_login}</span>
          </p>
          <UserMenu user={user} />
        </header>
        <div className="flex-1 px-8 py-8">{children}</div>
      </div>
    </div>
  );
}

function UserMenu({ user }: { user: AuthUser }) {
  const queryClient = useQueryClient();

  async function handleLogout() {
    try {
      await logout();
    } finally {
      clearSyncListCache();
      queryClient.clear();
    }
  }

  return (
    <details className="relative">
      <summary className="flex cursor-pointer list-none items-center gap-2 rounded-full py-1 pr-1 pl-1 text-sm text-[#fafafa] hover:bg-[#18181b] [&::-webkit-details-marker]:hidden">
        <span className="flex size-7 items-center justify-center rounded-full bg-[#164e63] text-xs font-medium text-[#67e8f9]">
          {initialsFromLogin(user.github_login)}
        </span>
        <span className="hidden sm:inline">{user.github_login}</span>
        <ChevronDown className="size-4 text-[#a1a1aa]" aria-hidden="true" />
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-40 rounded-lg border border-[#3f3f46] bg-[#18181b] p-1 shadow-lg">
        <button
          type="button"
          className="flex h-8 w-full items-center rounded-md px-2 text-sm text-[#fafafa] hover:bg-[#27272a]"
          onClick={() => {
            void handleLogout();
          }}
        >
          Log out
        </button>
      </div>
    </details>
  );
}
