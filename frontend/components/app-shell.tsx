"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { type ReactNode } from "react";
import { ChevronDown, LayoutGrid, ShieldCheck } from "lucide-react";

import { logout, type AuthUser } from "@/lib/api";
import { initialsFromLogin } from "@/lib/format";
import { cn } from "@/lib/utils";
import { useQueryClient } from "@tanstack/react-query";

export function AppShell({
  user,
  children,
}: {
  user: AuthUser;
  children: ReactNode;
}) {
  const pathname = usePathname();
  const reposCurrent = pathname === "/" || pathname.startsWith("/repositories");

  return (
    <div className="app-shell flex min-h-screen bg-[#09090b] text-[#fafafa]">
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:top-3 focus:left-3 focus:z-50 focus:rounded-md focus:bg-[#18181b] focus:px-3 focus:py-2 focus:text-sm focus:text-[#fafafa] focus:ring-2 focus:ring-[#22d3ee]/70"
      >
        Skip to content
      </a>
      <aside className="sticky top-0 flex h-screen w-56 shrink-0 flex-col border-r border-[#27272a] bg-[#09090b]">
        <div className="flex h-14 items-center gap-2.5 px-4">
          <ShieldCheck className="size-5 text-[#22d3ee]" strokeWidth={1.75} aria-hidden="true" />
          <span className="text-sm font-medium tracking-tight">CodeGuard AI</span>
        </div>
        <nav aria-label="Workspace" className="flex flex-1 flex-col px-3 py-2">
          <Link
            href="/"
            aria-current={reposCurrent ? "page" : undefined}
            className={cn(
              "flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm font-medium focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none",
              reposCurrent
                ? "bg-[#18181b] text-[#fafafa]"
                : "text-[#a1a1aa] hover:bg-[#18181b] hover:text-[#fafafa]",
            )}
          >
            <LayoutGrid className="size-4 text-[#a1a1aa]" aria-hidden="true" />
            Repositories
          </Link>
        </nav>
        <div className="border-t border-[#27272a] px-4 py-3 text-sm text-[#a1a1aa]">
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
        <main id="main-content" className="flex-1 px-8 py-8">
          {children}
        </main>
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
      queryClient.setQueryData(["auth", "me"], undefined);
      await queryClient.resetQueries({ queryKey: ["auth", "me"] });
    }
  }

  return (
    <details className="relative">
      <summary
        aria-label={`Account menu for ${user.github_login}`}
        className="flex cursor-pointer list-none items-center gap-2 rounded-full py-1 pr-1 pl-1 text-sm text-[#fafafa] hover:bg-[#18181b] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none [&::-webkit-details-marker]:hidden"
      >
        <span className="flex size-7 items-center justify-center rounded-full bg-[#164e63] text-xs font-medium text-[#67e8f9]">
          {initialsFromLogin(user.github_login)}
        </span>
        <span className="hidden sm:inline">{user.github_login}</span>
        <ChevronDown className="size-4 text-[#a1a1aa]" aria-hidden="true" />
      </summary>
      <div className="absolute right-0 z-50 mt-2 w-40 rounded-lg border border-[#3f3f46] bg-[#18181b] p-1 shadow-lg">
        <button
          type="button"
          className="flex h-8 w-full items-center rounded-md px-2 text-sm text-[#fafafa] hover:bg-[#27272a] focus-visible:bg-[#27272a] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
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
