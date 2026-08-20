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