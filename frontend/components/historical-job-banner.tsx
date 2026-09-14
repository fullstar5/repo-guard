"use client";

import Link from "next/link";

import { Button } from "@/components/ui/button";
import { formatRelativeTime } from "@/lib/format";

export function HistoricalJobBanner({
  jobId,
  updatedAt,
  latestHref,
  onBackToLatest,
}: {
  jobId: string | number;
  updatedAt?: string | null;
  latestHref: string;
  onBackToLatest?: () => void;
}) {
  return (
    <div className="mb-4 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#3f3f46] bg-[#18181b] px-3 py-2">
      <p className="text-sm text-[#a1a1aa]">
        Viewing job #{jobId}
        {updatedAt ? (
          <>
            <span className="mx-1.5 text-[#3f3f46]">·</span>
            {formatRelativeTime(updatedAt)}
          </>
        ) : null}
      </p>
      <Button asChild variant="outline" size="sm">
        <Link href={latestHref} onClick={onBackToLatest} className="focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70">
          Back to latest
        </Link>
      </Button>
    </div>
  );
}
