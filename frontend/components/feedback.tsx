import type { ReactNode } from "react";

import { LeanTable } from "@/components/lean-table";
import { cn } from "@/lib/utils";

export function TableSkeleton({
  rows = 6,
  columns = 3,
}: {
  rows?: number;
  columns?: number;
}) {
  return (
    <LeanTable>
      <div className="animate-pulse" aria-hidden="true">
        <div className="flex gap-4 border-b border-[#27272a] px-4 py-3">
          {Array.from({ length: columns }).map((_, index) => (
            <div
              key={`head-${index}`}
              className="h-3 flex-1 rounded bg-[#27272a]"
            />
          ))}
        </div>
        {Array.from({ length: rows }).map((_, row) => (
          <div
            key={`row-${row}`}
            className="flex gap-4 border-b border-[#27272a] px-4 py-3.5 last:border-b-0"
          >
            {Array.from({ length: columns }).map((_, col) => (
              <div
                key={`cell-${row}-${col}`}
                className={cn(
                  "h-4 rounded bg-[#27272a]",
                  col === 0 ? "flex-[2]" : "flex-1",
                )}
              />
            ))}
          </div>
        ))}
      </div>
      <p className="sr-only">Loading…</p>
    </LeanTable>
  );
}

export function PanelSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn(
        "flex min-h-[220px] flex-col gap-3 rounded-xl border border-[#3f3f46] bg-[#18181b]/40 p-5",
        className,
      )}
    >
      <div className="h-4 w-40 animate-pulse rounded bg-[#27272a]" />
      <div className="h-4 w-full animate-pulse rounded bg-[#27272a]" />
      <div className="h-4 w-5/6 animate-pulse rounded bg-[#27272a]" />
      <div className="h-4 w-2/3 animate-pulse rounded bg-[#27272a]" />
      <p className="sr-only">Loading…</p>
    </div>
  );
}

export function AppShellSkeleton() {
  return (
    <div className="flex min-h-screen bg-[#09090b]" aria-busy="true">
      <aside className="h-screen w-56 shrink-0 border-r border-[#27272a]" />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="h-14 border-b border-[#27272a]" />
        <div className="px-8 py-8">
          <div className="mb-6 h-8 w-48 animate-pulse rounded-md bg-[#27272a]" />
          <TableSkeleton />
        </div>
      </div>
      <p className="sr-only">Loading session…</p>
    </div>
  );
}

export function QueryError({
  message,
  onRetry,
}: {
  message: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-xl border border-[#7f1d1d]/70 bg-[#7f1d1d]/15 px-4 py-3">
      <p className="text-sm text-[#fca5a5]">{message}</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-2 text-sm text-[#67e8f9] hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function FilterEmpty({
  title,
  hint,
}: {
  title: string;
  hint: string;
}) {
  return (
    <div className="rounded-xl border border-dashed border-[#27272a] px-6 py-12 text-center">
      <p className="text-sm font-medium text-[#fafafa]">{title}</p>
      <p className="mt-1 text-sm text-[#a1a1aa]">{hint}</p>
    </div>
  );
}

export function RunningPanel({ children }: { children: ReactNode }) {
  return (
    <div className="flex min-h-[220px] flex-col items-center justify-center rounded-xl border border-[#3f3f46] bg-[#18181b]/40 px-6 py-12 text-center">
      <span
        className="size-5 animate-spin rounded-full border-2 border-[#22d3ee]/30 border-t-[#22d3ee]"
        aria-hidden="true"
      />
      <p className="mt-3 max-w-sm text-sm text-[#a1a1aa]">{children}</p>
    </div>
  );
}
