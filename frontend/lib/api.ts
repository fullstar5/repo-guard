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