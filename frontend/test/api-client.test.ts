import { beforeEach, describe, expect, it, vi } from "vitest";

const http = vi.hoisted(() => ({
  get: vi.fn(),
  post: vi.fn(),
}));

vi.mock("axios", () => ({
  default: {
    create: vi.fn(() => http),
  },
  isAxiosError: (error: unknown) =>
    Boolean(error && typeof error === "object" && "isAxiosError" in error),
}));

import {
  createReviewJob,
  getGitHubLoginUrl,
  getPullRequest,
  getPullRequestFile,
  getReviewJob,
  listPullRequestFiles,
  listPullRequests,
  listRepositories,
  listReviewJobs,
  listReviewModels,
  logout,
  syncPullRequestFiles,
  syncPullRequests,
  syncRepositories,
} from "@/lib/api";

beforeEach(() => {
  http.get.mockReset();
  http.post.mockReset();
});

describe("API client", () => {
  it("builds the GitHub login URL from the public API base", () => {
    expect(getGitHubLoginUrl()).toBe("/api/auth/github/login");
  });

  it("unwraps list payloads and posts sync/review bodies to the current routes", async () => {
    http.get.mockImplementation(async (url: string) => {
      if (url === "/repositories") {
        return { data: { count: 1, items: [{ id: 1 }] } };
      }
      if (url === "/repositories/4/pull-requests") {
        return { data: { count: 1, items: [{ id: 8 }] } };
      }
      if (url === "/pull-requests/8") {
        return { data: { id: 8, number: 3 } };
      }
      if (url === "/pull-requests/8/files") {
        return { data: { count: 1, items: [{ id: 9, filename: "a.py" }] } };
      }
      if (url === "/pull-requests/8/files/9") {
        return { data: { id: 9, patch: "@@" } };
      }
      if (url === "/pull-requests/8/review-jobs") {
        return { data: { count: 1, items: [{ id: 15 }] } };
      }
      if (url === "/review-jobs/15") {
        return { data: { id: 15, status: "completed" } };
      }
      if (url === "/review-models") {
        return { data: { models: ["openrouter/free"], default_model: "openrouter/free" } };
      }
      throw new Error(`unexpected GET ${url}`);
    });
    http.post.mockImplementation(async (url: string) => {
      if (url === "/auth/logout") {
        return { data: null };
      }
      if (url === "/repositories/sync") {
        return { data: { count: 1, items: [{ id: 2 }] } };
      }
      if (url === "/repositories/4/pr/sync") {
        return { data: { count: 0, items: [] } };
      }
      if (url === "/pull-requests/8/files/sync") {
        return { data: { count: 1, items: [{ id: 9 }] } };
      }
      if (url === "/pull-requests/8/review-jobs") {
        return { data: { id: 16, status: "pending" } };
      }
      throw new Error(`unexpected POST ${url}`);
    });

    await expect(listRepositories()).resolves.toEqual([{ id: 1 }]);
    await expect(syncRepositories()).resolves.toEqual([{ id: 2 }]);
    await expect(listPullRequests(4)).resolves.toEqual([{ id: 8 }]);
    await expect(syncPullRequests(4)).resolves.toEqual([]);
    await expect(getPullRequest(8)).resolves.toEqual({ id: 8, number: 3 });
    await expect(listPullRequestFiles(8)).resolves.toEqual([{ id: 9, filename: "a.py" }]);
    await expect(getPullRequestFile(8, 9)).resolves.toEqual({ id: 9, patch: "@@" });
    await expect(syncPullRequestFiles(8)).resolves.toEqual([{ id: 9 }]);
    await expect(listReviewJobs(8)).resolves.toEqual([{ id: 15 }]);
    await expect(getReviewJob(15)).resolves.toEqual({ id: 15, status: "completed" });
    await expect(listReviewModels()).resolves.toEqual({
      models: ["openrouter/free"],
      default_model: "openrouter/free",
    });
    await logout();

    await expect(createReviewJob(8, "nvidia/nemotron-3-ultra-550b-a55b:free")).resolves.toEqual({
      id: 16,
      status: "pending",
    });
    expect(http.post).toHaveBeenCalledWith("/pull-requests/8/review-jobs", {
      provider: "openrouter",
      model_name: "nvidia/nemotron-3-ultra-550b-a55b:free",
    });
  });
});
