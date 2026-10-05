import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import HomePage from "@/app/page";
import RepositoryPage from "@/app/repositories/[repoId]/page";
import PullRequestPage from "@/app/repositories/[repoId]/pull-requests/[prId]/page";
import FilePage from "@/app/repositories/[repoId]/pull-requests/[prId]/files/[fileId]/page";
import { ToastProvider } from "@/components/toast";
import type { ReviewJob } from "@/lib/api";
import {
  createReviewJob,
  getPullRequest,
  getPullRequestFile,
  listPullRequestFiles,
  listPullRequests,
  listRepositories,
  listReviewJobs,
  listReviewModels,
  syncPullRequestFiles,
  syncPullRequests,
  syncRepositories,
} from "@/lib/api";

const nav = vi.hoisted(() => ({
  params: { repoId: "4", prId: "8", fileId: "3" },
  search: "",
  pathname: "/",
  replace: vi.fn(),
}));

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
  useParams: () => nav.params,
  usePathname: () => nav.pathname,
  useRouter: () => ({ replace: nav.replace, push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(nav.search),
}));

vi.mock("@/components/auth-gate", () => ({
  AuthGate: ({ children }: { children: ReactNode }) => children,
}));

vi.mock("@/lib/api", () => ({
  getCurrentUser: vi.fn(),
  logout: vi.fn(),
  getGitHubLoginUrl: () => "/api/auth/github/login",
  listRepositories: vi.fn(),
  syncRepositories: vi.fn(),
  listPullRequests: vi.fn(),
  syncPullRequests: vi.fn(),
  getPullRequest: vi.fn(),
  getPullRequestFile: vi.fn(),
  listPullRequestFiles: vi.fn(),
  syncPullRequestFiles: vi.fn(),
  listReviewJobs: vi.fn(),
  listReviewModels: vi.fn(),
  createReviewJob: vi.fn(),
  getReviewJob: vi.fn(),
  api: { get: vi.fn(), post: vi.fn() },
}));

const user = {
  id: 1,
  github_id: 9,
  github_login: "octo",
  email: null,
};

function renderPage(ui: ReactNode) {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
    },
  });
  client.setQueryData(["auth", "me"], user);
  const view = render(
    <QueryClientProvider client={client}>
      <ToastProvider>{ui}</ToastProvider>
    </QueryClientProvider>,
  );
  return { client, ...view };
}

function reviewJob(partial: Partial<ReviewJob> & Pick<ReviewJob, "id" | "status" | "updated_at">): ReviewJob {
  return {
    pull_request_id: 8,
    provider: "openrouter",
    model_name: "openrouter/free",
    total_files: 1,
    total_chunks: 1,
    error_message: null,
    result_summary: partial.status === "completed" ? "summary" : null,
    findings: [],
    created_at: "2026-06-01T00:00:00Z",
    ...partial,
  };
}

beforeEach(() => {
  nav.params = { repoId: "4", prId: "8", fileId: "3" };
  nav.search = "";
  nav.pathname = "/";
  nav.replace.mockReset();
  vi.mocked(listRepositories).mockReset();
  vi.mocked(syncRepositories).mockReset();
  vi.mocked(listPullRequests).mockReset();
  vi.mocked(syncPullRequests).mockReset();
  vi.mocked(getPullRequest).mockReset();
  vi.mocked(getPullRequestFile).mockReset();
  vi.mocked(listPullRequestFiles).mockReset();
  vi.mocked(syncPullRequestFiles).mockReset();
  vi.mocked(listReviewJobs).mockReset();
  vi.mocked(listReviewModels).mockReset();
  vi.mocked(createReviewJob).mockReset();
});

describe("sync writes the query cache for the active list", () => {
  it("replaces the repository cache from the sync response", async () => {
    vi.mocked(listRepositories).mockResolvedValue([
      {
        id: 1,
        github_repo_id: 11,
        name: "old",
        full_name: "octo/old",
        owner_login: "octo",
        private: false,
        default_branch: "main",
        updated_at: "2026-06-01T00:00:00Z",
      },
    ]);
    vi.mocked(syncRepositories).mockResolvedValue([
      {
        id: 2,
        github_repo_id: 22,
        name: "fresh",
        full_name: "octo/fresh",
        owner_login: "octo",
        private: true,
        default_branch: "main",
        updated_at: "2026-06-02T00:00:00Z",
      },
    ]);

    const { client } = renderPage(<HomePage />);
    expect(await screen.findByText("octo/old")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sync repositories" }));

    expect(await screen.findByText("octo/fresh")).toBeInTheDocument();
    expect(screen.queryByText("octo/old")).not.toBeInTheDocument();
    expect(client.getQueryData(["repositories"])).toEqual([
      expect.objectContaining({ full_name: "octo/fresh" }),
    ]);
    expect(listRepositories).toHaveBeenCalledOnce();
    expect(await screen.findByText("Repositories updated.")).toBeInTheDocument();
  });

  it("replaces the pull request cache for that repository", async () => {
    nav.pathname = "/repositories/4";
    vi.mocked(listRepositories).mockResolvedValue([]);
    vi.mocked(listPullRequests).mockResolvedValue([
      {
        id: 8,
        github_pr_id: 80,
        number: 1,
        title: "Old pull request",
        state: "open",
        author_login: "octo",
        html_url: "https://github.com/octo/demo/pull/1",
        base_branch: "main",
        head_branch: "old",
        is_draft: false,
        github_updated_at: "2026-06-01T00:00:00Z",
      },
    ]);
    vi.mocked(syncPullRequests).mockResolvedValue([
      {
        id: 9,
        github_pr_id: 90,
        number: 2,
        title: "Fresh pull request",
        state: "open",
        author_login: "octo",
        html_url: "https://github.com/octo/demo/pull/2",
        base_branch: "main",
        head_branch: "fresh",
        is_draft: false,
        github_updated_at: "2026-06-02T00:00:00Z",
      },
    ]);

    const { client } = renderPage(<RepositoryPage />);
    expect(await screen.findByText("Old pull request")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sync pull requests" }));
    expect(await screen.findByText("Fresh pull request")).toBeInTheDocument();
    expect(screen.queryByText("Old pull request")).not.toBeInTheDocument();
    expect(client.getQueryData(["repositories", 4, "pull-requests"])).toEqual([
      expect.objectContaining({ title: "Fresh pull request" }),
    ]);
    expect(listPullRequests).toHaveBeenCalledOnce();
  });

  it("replaces the changed-file cache after sync files", async () => {
    nav.pathname = "/repositories/4/pull-requests/8";
    nav.search = "tab=files";
    vi.mocked(listRepositories).mockResolvedValue([]);
    vi.mocked(getPullRequest).mockResolvedValue({
      id: 8,
      github_pr_id: 80,
      number: 3,
      title: "Review me",
      state: "open",
      author_login: "octo",
      html_url: "https://github.com/octo/demo/pull/3",
      base_branch: "main",
      head_branch: "feature",
      is_draft: false,
      github_updated_at: "2026-06-01T00:00:00Z",
    });
    vi.mocked(listPullRequestFiles).mockResolvedValue([
      {
        id: 1,
        filename: "old.py",
        previous_filename: null,
        status: "modified",
        additions: 1,
        deletions: 0,
        changes: 1,
      },
    ]);
    vi.mocked(syncPullRequestFiles).mockResolvedValue([
      {
        id: 2,
        filename: "fresh.py",
        previous_filename: null,
        status: "added",
        additions: 2,
        deletions: 0,
        changes: 2,
      },
    ]);
    vi.mocked(listReviewJobs).mockResolvedValue([]);
    vi.mocked(listReviewModels).mockResolvedValue({
      models: ["openrouter/free"],
      default_model: "openrouter/free",
    });

    const { client } = renderPage(<PullRequestPage />);
    expect(await screen.findByText("old.py")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Sync files" }));
    expect(await screen.findByText("fresh.py")).toBeInTheDocument();
    expect(screen.queryByText("old.py")).not.toBeInTheDocument();
    expect(client.getQueryData(["pull-requests", 8, "files"])).toEqual([
      expect.objectContaining({ filename: "fresh.py" }),
    ]);
    expect(listPullRequestFiles).toHaveBeenCalledOnce();
  });
});

describe("pull request review pin", () => {
  const pinned = reviewJob({
    id: 1,
    status: "completed",
    updated_at: "2026-06-01T00:00:00Z",
    findings: [
      {
        id: 11,
        severity: "high",
        summary: "pinned finding",
        file_path: null,
        pr_file_id: null,
        start_line: null,
        end_line: null,
        suggestion: "pin the check",
        created_at: "2026-06-01T00:00:00Z",
        updated_at: "2026-06-01T00:00:00Z",
      },
    ],
  });
  const latest = reviewJob({
    id: 2,
    status: "completed",
    updated_at: "2026-06-10T00:00:00Z",
    findings: [
      {
        id: 22,
        severity: "low",
        summary: "latest finding",
        file_path: null,
        pr_file_id: null,
        start_line: null,
        end_line: null,
        suggestion: null,
        created_at: "2026-06-10T00:00:00Z",
        updated_at: "2026-06-10T00:00:00Z",
      },
    ],
  });

  function ready() {
    vi.mocked(listRepositories).mockResolvedValue([]);
    vi.mocked(getPullRequest).mockResolvedValue({
      id: 8,
      github_pr_id: 80,
      number: 3,
      title: "Review me",
      state: "open",
      author_login: "octo",
      html_url: "https://github.com/octo/demo/pull/3",
      base_branch: "main",
      head_branch: "feature",
      is_draft: false,
      github_updated_at: "2026-06-01T00:00:00Z",
    });
    vi.mocked(listPullRequestFiles).mockResolvedValue([
      {
        id: 3,
        filename: "a.py",
        previous_filename: null,
        status: "modified",
        additions: 1,
        deletions: 0,
        changes: 1,
      },
    ]);
    vi.mocked(listReviewJobs).mockResolvedValue([pinned, latest]);
    vi.mocked(listReviewModels).mockResolvedValue({
      models: ["openrouter/free"],
      default_model: "openrouter/free",
    });
  }

  it("shows the pinned job and removes the pin from other tab links", async () => {
    nav.pathname = "/repositories/4/pull-requests/8";
    nav.search = "tab=review&jobId=1&finding=11";
    ready();
    renderPage(<PullRequestPage />);

    expect(await screen.findAllByText("pinned finding")).not.toHaveLength(0);
    expect(screen.queryAllByText("latest finding")).toHaveLength(0);
    expect(screen.getByText(/Viewing job #1/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to latest" })).toHaveAttribute(
      "href",
      "?tab=review",
    );
    expect(screen.getByRole("tab", { name: "files" })).toHaveAttribute("href", "?tab=files");
  });

  it("uses the latest completed job when nothing is pinned", async () => {
    nav.pathname = "/repositories/4/pull-requests/8";
    nav.search = "tab=review";
    ready();
    renderPage(<PullRequestPage />);
    expect(await screen.findAllByText("latest finding")).not.toHaveLength(0);
    expect(screen.queryByText(/Viewing job #/)).not.toBeInTheDocument();
  });

  it("does not render another job when the pinned id is missing", async () => {
    nav.pathname = "/repositories/4/pull-requests/8";
    nav.search = "tab=review&jobId=99";
    ready();
    renderPage(<PullRequestPage />);
    expect(
      await screen.findByText("Review job #99 was not found for this pull request."),
    ).toBeInTheDocument();
    expect(screen.queryAllByText("latest finding")).toHaveLength(0);
    expect(screen.queryAllByText("pinned finding")).toHaveLength(0);
  });

  it("clears a historical pin after queueing a new review", async () => {
    nav.pathname = "/repositories/4/pull-requests/8";
    nav.search = "tab=review&jobId=1";
    ready();
    vi.mocked(createReviewJob).mockResolvedValue(
      reviewJob({ id: 5, status: "pending", updated_at: "2026-06-15T00:00:00Z" }),
    );
    const { client } = renderPage(<PullRequestPage />);
    const invalidate = vi.spyOn(client, "invalidateQueries");
    expect(await screen.findAllByText("pinned finding")).not.toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Run AI review" }));
    await waitFor(() => {
      expect(createReviewJob).toHaveBeenCalledWith(8, "openrouter/free");
      expect(invalidate).toHaveBeenCalledWith({
        queryKey: ["pull-requests", 8, "review-jobs"],
      });
      expect(nav.replace).toHaveBeenCalledWith("/repositories/4/pull-requests/8?tab=review", {
        scroll: false,
      });
    });
  });
});

describe("file diff does not borrow findings from another job", () => {
  it("shows the pinned job's finding and a not-found state for an unknown pin", async () => {
    nav.pathname = "/repositories/4/pull-requests/8/files/3";
    nav.search = "jobId=1";
    vi.mocked(listRepositories).mockResolvedValue([]);
    vi.mocked(getPullRequest).mockResolvedValue({
      id: 8,
      github_pr_id: 80,
      number: 3,
      title: "Review me",
      state: "open",
      author_login: "octo",
      html_url: "https://github.com/octo/demo/pull/3",
      base_branch: "main",
      head_branch: "feature",
      is_draft: false,
      github_updated_at: "2026-06-01T00:00:00Z",
    });
    vi.mocked(getPullRequestFile).mockResolvedValue({
      id: 3,
      filename: "a.py",
      previous_filename: null,
      status: "modified",
      additions: 1,
      deletions: 1,
      changes: 2,
      sha: "abc",
      blob_url: null,
      patch: "@@ -1 +1 @@\n-old\n+new\n",
    });
    vi.mocked(listReviewJobs).mockResolvedValue([
      reviewJob({
        id: 1,
        status: "completed",
        updated_at: "2026-06-01T00:00:00Z",
        findings: [
          {
            id: 11,
            severity: "high",
            summary: "pinned file finding",
            file_path: "a.py",
            pr_file_id: 3,
            start_line: 1,
            end_line: 1,
            suggestion: null,
            created_at: "2026-06-01T00:00:00Z",
            updated_at: "2026-06-01T00:00:00Z",
          },
        ],
      }),
      reviewJob({
        id: 2,
        status: "completed",
        updated_at: "2026-06-10T00:00:00Z",
        findings: [
          {
            id: 22,
            severity: "low",
            summary: "other job finding",
            file_path: "a.py",
            pr_file_id: 3,
            start_line: 1,
            end_line: 1,
            suggestion: null,
            created_at: "2026-06-10T00:00:00Z",
            updated_at: "2026-06-10T00:00:00Z",
          },
        ],
      }),
    ]);

    const view = renderPage(<FilePage />);
    expect(await screen.findAllByText("pinned file finding")).not.toHaveLength(0);
    expect(screen.queryAllByText("other job finding")).toHaveLength(0);

    view.unmount();
    nav.search = "jobId=99";
    renderPage(<FilePage />);
    expect(
      await screen.findByText("Review job #99 was not found for this pull request."),
    ).toBeInTheDocument();
    expect(screen.queryAllByText("pinned file finding")).toHaveLength(0);
    expect(screen.queryAllByText("other job finding")).toHaveLength(0);
  });
});
