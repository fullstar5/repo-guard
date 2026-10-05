import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { AppShell } from "@/components/app-shell";
import { HistoricalJobBanner } from "@/components/historical-job-banner";
import { Providers } from "@/components/providers";
import { ReviewJobsTable } from "@/components/review-jobs-table";
import { SyncButton } from "@/components/sync-button";
import type { ReviewJob } from "@/lib/api";
import { logout } from "@/lib/api";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    scroll,
    ...rest
  }: {
    href: string;
    children: ReactNode;
    scroll?: boolean;
  }) => {
    void scroll;
    return (
      <a href={href} {...rest}>
        {children}
      </a>
    );
  },
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/",
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    logout: vi.fn(),
  };
});

function job(partial: Partial<ReviewJob> & Pick<ReviewJob, "id" | "status">): ReviewJob {
  return {
    pull_request_id: 8,
    provider: "openrouter",
    model_name: "openrouter/free",
    total_files: 1,
    total_chunks: 1,
    error_message: null,
    result_summary: null,
    findings: [],
    created_at: "2026-06-15T12:00:00Z",
    updated_at: "2026-06-15T12:01:05Z",
    ...partial,
  };
}

describe("Sync button", () => {
  it("shows the idle label and calls onClick", () => {
    const onClick = vi.fn();
    render(<SyncButton pending={false} onClick={onClick} />);
    fireEvent.click(screen.getByRole("button", { name: "Sync" }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it("disables itself and announces the pending label", () => {
    const onClick = vi.fn();
    render(
      <SyncButton
        pending
        onClick={onClick}
        idleLabel="Sync"
        pendingLabel="Syncing…"
        aria-label="Syncing files"
      />,
    );
    const button = screen.getByRole("button", { name: "Syncing files" });
    expect(button).toBeDisabled();
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toHaveTextContent("Syncing…");
    fireEvent.click(button);
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe("Review jobs table", () => {
  it("renders an empty state", () => {
    render(
      <ReviewJobsTable
        jobs={[]}
        hrefForJob={() => "?tab=review"}
        onRetry={vi.fn()}
        retryDisabled={false}
        retryPending={false}
      />,
    );
    expect(screen.getByText("No review jobs yet.")).toBeInTheDocument();
  });

  it("hides retry and counts while a job is active, and pins the selected row", () => {
    const onRetry = vi.fn();
    const jobs = [
      job({ id: 1, status: "pending", findings: [] }),
      job({
        id: 2,
        status: "completed",
        findings: [
          {
            id: 9,
            severity: "high",
            summary: "bug",
            file_path: "a.py",
            pr_file_id: 1,
            start_line: 1,
            end_line: 1,
            suggestion: null,
            created_at: "2026-06-15T12:00:00Z",
            updated_at: "2026-06-15T12:01:05Z",
          },
        ],
      }),
    ];
    render(
      <ReviewJobsTable
        jobs={jobs}
        selectedJobId={2}
        hrefForJob={(item) => `?tab=review&jobId=${item.id}`}
        onRetry={onRetry}
        retryDisabled={false}
        retryPending={false}
      />,
    );

    expect(screen.getByRole("link", { name: "job_1" })).toHaveAttribute(
      "href",
      "?tab=review&jobId=1",
    );
    expect(screen.getByText("Queued")).toBeInTheDocument();
    expect(screen.getAllByText("Free router").length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Retry job 1" })).not.toBeInTheDocument();
    expect(screen.getByText("1:05")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry job 2" }));
    expect(onRetry).toHaveBeenCalledOnce();
  });
});

describe("Historical job banner", () => {
  it("names the pinned job and links back to the latest review", () => {
    render(
      <HistoricalJobBanner
        jobId={12}
        updatedAt="2026-06-01T00:00:00Z"
        latestHref="?tab=review"
      />,
    );
    expect(screen.getByText(/Viewing job #12/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to latest" })).toHaveAttribute(
      "href",
      "?tab=review",
    );
  });
});

describe("session query cache", () => {
  it("clears the auth query when the user logs out", async () => {
    vi.mocked(logout).mockResolvedValue();
    const client = new QueryClient();
    client.setQueryData(["auth", "me"], {
      id: 1,
      github_id: 1,
      github_login: "octo",
      email: null,
    });
    render(
      <QueryClientProvider client={client}>
        <AppShell
          user={{ id: 1, github_id: 1, github_login: "octo", email: null }}
        >
          <p>workspace</p>
        </AppShell>
      </QueryClientProvider>,
    );

    fireEvent.click(screen.getByLabelText("Account menu for octo"));
    fireEvent.click(screen.getByRole("button", { name: "Log out" }));
    await vi.waitFor(() => {
      expect(logout).toHaveBeenCalledOnce();
      expect(client.getQueryData(["auth", "me"])).toBeUndefined();
    });
  });

  it("uses a short stale time and does not retry queries by default", () => {
    const seen: { client?: QueryClient } = {};
    function Probe() {
      seen.client = useQueryClient();
      return null;
    }
    render(
      <Providers>
        <Probe />
      </Providers>,
    );
    expect(seen.client?.getDefaultOptions().queries?.staleTime).toBe(30_000);
    expect(seen.client?.getDefaultOptions().queries?.retry).toBe(false);
  });
});
