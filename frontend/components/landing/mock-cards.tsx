import { File } from "lucide-react";
import type { ReactNode } from "react";

import styles from "./landing.module.css";

function MockCard({ children }: { children: ReactNode }) {
  return <div className={styles.glass}>{children}</div>;
}

export function ReviewMockCard() {
  return (
    <MockCard>
      <div className="flex items-start justify-between gap-3 border-b border-[#3f3f46] px-4 py-3">
        <div className="min-w-0">
          <p className="truncate text-[13px] font-medium text-[#fafafa]">
            Harden auth middleware…
          </p>
          <p className="mt-0.5 truncate text-[11px] text-[#a1a1aa]">
            PR #18 · fix/auth-refresh-race
          </p>
        </div>
        <div className="shrink-0 text-right">
          <p className="text-[9px] font-medium tracking-[0.12em] text-[#71717a]">
            CONFIDENCE
          </p>
          <p className="text-sm font-semibold tabular-nums text-[#fafafa]">
            3/5
          </p>
        </div>
      </div>

      <div className="flex flex-wrap gap-1.5 px-4 py-3">
        <span className="rounded-full bg-[#7f1d1d]/80 px-2 py-0.5 text-[11px] font-medium text-[#fecaca]">
          1 Critical
        </span>
        <span className="rounded-full bg-[#9a3412]/80 px-2 py-0.5 text-[11px] font-medium text-[#fed7aa]">
          1 High
        </span>
        <span className="rounded-full bg-[#854d0e]/70 px-2 py-0.5 text-[11px] font-medium text-[#fde68a]">
          2 Medium
        </span>
      </div>

      <div className="relative mx-4 overflow-hidden rounded-[8px] border border-[#3f3f46] bg-[#09090b] font-mono text-[12px] leading-5">
        <div className="absolute inset-y-0 left-0 w-[3px] bg-[#22d3ee]" />
        <div className="px-3 py-2 text-[#a1a1aa]">
          <div>
            <span className="inline-block w-6 text-right text-[#52525b]">
              84
            </span>{" "}
            async function refresh(userId) {"{"}
          </div>
          <div className="bg-[#7f1d1d]/45 text-[#fca5a5]">
            <span className="inline-block w-6 text-right text-[#52525b]">
              85
            </span>{" "}
            - const token = await getToken(userId)
          </div>
          <div className="bg-[#14532d]/50 text-[#86efac]">
            <span className="inline-block w-6 text-right text-[#52525b]">
              85
            </span>{" "}
            + await mutex.acquire(userId)
          </div>
          <div className="bg-[#14532d]/50 text-[#86efac]">
            <span className="inline-block w-6 text-right text-[#52525b]">
              86
            </span>{" "}
            + const token = await getToken(userId)
          </div>
          <div>
            <span className="inline-block w-6 text-right text-[#52525b]">
              87
            </span>{" "}
            if (token.expired) {"{"}
          </div>
          <div className="bg-[#14532d]/50 text-[#86efac]">
            <span className="inline-block w-6 text-right text-[#52525b]">
              88
            </span>{" "}
            + await revokePrev(token)
          </div>
        </div>
      </div>

      <div className="m-4 rounded-[8px] border border-[#3f3f46] bg-[#27272a] px-3 py-2.5">
        <p className="text-[12px] font-medium text-[#fafafa]">
          Token refresh race can issue duplicate sessions
        </p>
        <p className="mt-1 text-[11px] leading-4 text-[#a1a1aa]">
          Guard the refresh path with Mutex keyed by userId…
        </p>
      </div>
    </MockCard>
  );
}

const FILES = [
  { name: "src/auth/middleware.ts", add: 42, del: 18 },
  { name: "src/auth/mutex.ts", add: 68, del: 0 },
  { name: "src/auth/token.ts", add: 24, del: 31 },
  { name: "src/auth/__tests__/refresh.test.ts", add: 38, del: 4 },
  { name: "package.json", add: 2, del: 1 },
  { name: "README.md", add: 10, del: 7 },
] as const;

export function FilesMockCard() {
  return (
    <MockCard>
      <div className="flex items-center justify-between border-b border-[#3f3f46] px-4 py-3">
        <div className="flex items-center gap-2">
          <span className="size-1.5 rounded-full bg-[#4ade80] shadow-[0_0_8px_rgb(74_222_128_/_0.8)]" />
          <p className="text-[13px] font-medium text-[#fafafa]">Files</p>
        </div>
        <p className="text-[11px] text-[#a1a1aa]">6 changed</p>
      </div>

      <div className="flex items-baseline justify-between px-4 py-3">
        <p className="text-sm font-medium text-[#fafafa]">6 files</p>
        <p className="font-mono text-[12px] tabular-nums">
          <span className="text-[#4ade80]">+184</span>{" "}
          <span className="text-[#f87171]">-61</span>
        </p>
      </div>

      <ul className="divide-y divide-[#27272a] px-1 pb-2">
        {FILES.map((file) => (
          <li
            key={file.name}
            className="flex items-center justify-between gap-3 px-3 py-2"
          >
            <span className="flex min-w-0 items-center gap-2 text-[13px] text-[#e4e4e7]">
              <File className="size-3.5 shrink-0 text-[#a1a1aa]" aria-hidden="true" />
              <span className="truncate font-mono">{file.name}</span>
            </span>
            <span className="shrink-0 font-mono text-[11px] tabular-nums">
              <span className="text-[#4ade80]">+{file.add}</span>{" "}
              <span className="text-[#f87171]">-{file.del}</span>
            </span>
          </li>
        ))}
      </ul>
    </MockCard>
  );
}

const JOBS = [
  {
    title: "Harden auth middleware",
    meta: "PR #18 · 6 files",
    status: "success" as const,
  },
  {
    title: "Token refresh race",
    meta: "PR #18 · chunk 2/4",
    status: "processing" as const,
  },
  {
    title: "Missing revoke on expiry",
    meta: "PR #17 · queued",
    status: "pending" as const,
  },
  {
    title: "Log PII in auth retry",
    meta: "PR #16 · timeout",
    status: "failed" as const,
  },
] as const;

const STATUS_STYLES: Record<
  (typeof JOBS)[number]["status"],
  { label: string; className: string; dot: string }
> = {
  pending: {
    label: "Pending",
    className: "text-[#a1a1aa] bg-[#27272a]",
    dot: "bg-[#a1a1aa]",
  },
  processing: {
    label: "Processing",
    className: "text-[#67e8f9] bg-[#164e63]/50",
    dot: "bg-[#22d3ee]",
  },
  success: {
    label: "Success",
    className: "text-[#86efac] bg-[#14532d]/50",
    dot: "bg-[#4ade80]",
  },
  failed: {
    label: "Failed",
    className: "text-[#fca5a5] bg-[#7f1d1d]/45",
    dot: "bg-[#f87171]",
  },
};

export function JobsMockCard() {
  return (
    <MockCard>
      <div className="flex items-center justify-between border-b border-[#3f3f46] px-4 py-3">
        <p className="text-[13px] font-medium text-[#fafafa]">Jobs</p>
        <p className="text-[11px] text-[#a1a1aa]">4 recent</p>
      </div>
      <ul className="divide-y divide-[#27272a] p-1">
        {JOBS.map((job) => {
          const status = STATUS_STYLES[job.status];
          return (
            <li
              key={job.title}
              className="flex items-center justify-between gap-3 px-3 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-[12px] font-medium text-[#fafafa]">
                  {job.title}
                </p>
                <p className="mt-0.5 truncate text-[11px] text-[#71717a]">
                  {job.meta}
                </p>
              </div>
              <span
                className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2 py-0.5 text-[10px] font-medium ${status.className}`}
              >
                <span className={`size-1.5 rounded-full ${status.dot}`} />
                {status.label}
              </span>
            </li>
          );
        })}
      </ul>
    </MockCard>
  );
}
