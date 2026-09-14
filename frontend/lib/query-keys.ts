export const repositoryListKey = ["repositories"] as const;

export function pullRequestListKey(repositoryId: number) {
  return ["repositories", repositoryId, "pull-requests"] as const;
}

export function pullRequestFilesKey(pullRequestId: number) {
  return ["pull-requests", pullRequestId, "files"] as const;
}

export function reviewJobsKey(pullRequestId: number) {
  return ["pull-requests", pullRequestId, "review-jobs"] as const;
}
