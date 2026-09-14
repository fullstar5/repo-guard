"use client";

import { RefreshCw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function SyncButton({
  pending,
  onClick,
  idleLabel = "Sync",
  pendingLabel = "Syncing…",
  className,
}: {
  pending: boolean;
  onClick: () => void;
  idleLabel?: string;
  pendingLabel?: string;
  className?: string;
}) {
  return (
    <Button
      type="button"
      variant="secondary"
      onClick={onClick}
      disabled={pending}
      aria-busy={pending}
      className={cn(
        "border border-[#22d3ee]/45 bg-[#18181b] text-[#fafafa] hover:border-[#22d3ee]/80 hover:bg-[#27272a] disabled:opacity-80",
        className,
      )}
    >
      <RefreshCw
        className={cn("size-4 text-[#22d3ee]", pending && "animate-spin")}
        aria-hidden="true"
      />
      {pending ? pendingLabel : idleLabel}
    </Button>
  );
}
