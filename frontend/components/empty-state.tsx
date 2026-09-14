import type { ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function EmptyState({
  icon,
  title,
  hint,
  actionLabel,
  onAction,
  actionPending,
}: {
  icon: ReactNode;
  title: string;
  hint: string;
  actionLabel?: string;
  onAction?: () => void;
  actionPending?: boolean;
}) {
  return (
    <div className="flex min-h-[420px] flex-col items-center justify-center rounded-xl border border-[#27272a] bg-[#18181b]/40 px-6 py-16 text-center">
      <div className="mb-5 flex size-16 items-center justify-center rounded-full border border-dashed border-[#22d3ee]/40 bg-[#09090b]">
        {icon}
      </div>
      <p className="text-base font-medium text-[#fafafa]">{title}</p>
      <p className="mt-2 max-w-sm text-sm text-[#a1a1aa]">{hint}</p>
      {actionLabel && onAction ? (
        <Button
          className="mt-6"
          onClick={onAction}
          disabled={actionPending}
        >
          {actionPending ? "Syncing..." : actionLabel}
        </Button>
      ) : null}
    </div>
  );
}

export function InlineStatus({
  children,
  tone = "muted",
}: {
  children: ReactNode;
  tone?: "muted" | "danger";
}) {
  return (
    <p
      className={cn(
        "text-sm",
        tone === "danger" ? "text-[#fca5a5]" : "text-[#a1a1aa]",
      )}
    >
      {children}
    </p>
  );
}
