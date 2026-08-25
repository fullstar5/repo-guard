import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL;

if (!API_URL) {
    throw new Error(
        "NEXT_PUBLIC_API_URL is not set. Add it to frontend/.env.local and restart next dev.",
    );
}

export const api = axios.create({
    baseURL: API_URL,
    withCredentials: true,
});

export type AuthUser = {
    id: number,
    github_id: number,
    github_login: string;
    email: string | null;
};

export async function getCurrentUser(): Promise<AuthUser> {
    const res = await api.get<AuthUser>("/auth/me");
    return res.data;
}

export async function logout(): Promise<void> {
    await api.post("/auth/logout");
}

export function getGitHubLoginUrl(): string {
    return `${API_URL}/auth/github/login`;
}


export type Repository = {
    id: number;
    github_repo_id: number;
    name: string;
    full_name: string;
    owner_login: string;
    private: boolean;
    default_branch: string | null;
};
  
export type PullRequest = {
    id: number;
    github_pr_id: number;
    number: number;
    title: string;
    state: string;
    author_login: string | null;
    html_url: string;
    base_branch: string;
    head_branch: string;
    is_draft: boolean;
};


export type PullRequestFile = {
    id: number;
    filename: string;
    previous_filename: string | null;
    status: string;
    additions: number;
    deletions: number;
    changes: number;
};

export type PullRequestFileDetail = PullRequestFile & {
    sha: string | null;
    blob_url: string | null;
    patch: string | null;
};


export type ReviewJobStatus = "pending" | "processing" | "completed" | "failed";

export type ReviewFindingSeverity = "low" | "medium" | "high" | "critical";


export type ReviewFinding = {
    id: number;
    severity: ReviewFindingSeverity;
    summary: string;
    file_path: string | null;
    pr_file_id: number | null;
    start_line: number | null;
    end_line: number | null;
    suggestion: string | null;
    created_at: string;
    updated_at: string;
}


export type ReviewJob = {
    id: number;
    pull_request_id: number;
    status: ReviewJobStatus;
    provider: string;
    model_name: string;
    total_files: number;
    total_chunks: number;
    error_message: string | null;
    result_summary: string | null;
    findings: ReviewFinding[];
    created_at: string;
    updated_at: string;
};

type ListResponse<T> = {
    count: number;
    items: T[];
};
  






export async function listRepositories(): Promise<Repository[]> {
    const response = await api.get<ListResponse<Repository>>("/repositories");
    return response.data.items;
}
  
export async function syncRepositories(): Promise<Repository[]> {
    const response = await api.post<ListResponse<Repository>>("/repositories/sync");
    return response.data.items;
}
  
export async function listPullRequests(repositoryId: number): Promise<PullRequest[]> {
    const response = await api.get<ListResponse<PullRequest>>(
      `/repositories/${repositoryId}/pull-requests`,
    );
    return response.data.items;
}
  
export async function syncPullRequests(repositoryId: number): Promise<PullRequest[]> {
    const response = await api.post<ListResponse<PullRequest>>(
      `/repositories/${repositoryId}/pr/sync`,
    );
    return response.data.items;
}


export async function getPullRequest(pullRequestId: number): Promise<PullRequest> {
    const response = await api.get<PullRequest>(`/pull-requests/${pullRequestId}`);
    return response.data;
}

export async function getPullRequestFile(
    pullRequestId: number,
    fileId: number,
): Promise<PullRequestFileDetail> {
    const response = await api.get<PullRequestFileDetail>(
        `/pull-requests/${pullRequestId}/files/${fileId}`,
    );
    return response.data;
}

export async function listPullRequestFiles(pullRequestId: number): Promise<PullRequestFile[]> {
    const response = await api.get<ListResponse<PullRequestFile>>(
        `/pull-requests/${pullRequestId}/files`,
    );
    return response.data.items;
}

export async function syncPullRequestFiles(pullRequestId: number): Promise<PullRequestFile[]> {
    const response = await api.post<ListResponse<PullRequestFile>>(
        `/pull-requests/${pullRequestId}/files/sync`,
    );
    return response.data.items;
}

export async function listReviewJobs(pullRequestId: number): Promise<ReviewJob[]> {
    const response = await api.get<ListResponse<ReviewJob>>(
        `/pull-requests/${pullRequestId}/review-jobs`,
    );
    return response.data.items;
}


export async function createReviewJob(pullRequestId: number): Promise<ReviewJob> {
    const response = await api.post<ReviewJob>(
        `/pull-requests/${pullRequestId}/review-jobs`,
        {
            provider: "openrouter",
            model_name: "openrouter/free",
        },
    );
    return response.data;
}


export async function getReviewJob(reviewJobId: number): Promise<ReviewJob> {
    const response = await api.get<ReviewJob>(`/review-jobs/${reviewJobId}`)
    return response.data;
}