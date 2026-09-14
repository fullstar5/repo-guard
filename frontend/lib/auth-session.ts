import { getCurrentUser } from "./api";

export const authMeQueryOptions = {
  queryKey: ["auth", "me"] as const,
  queryFn: getCurrentUser,
  refetchOnWindowFocus: false,
};

/**
 * True only for the first in-flight /auth/me request.
 * Window-focus refetches must not remount the full-screen session gate.
 */
export function isInitialAuthPending(query: {
  isFetched: boolean;
  isPending: boolean;
}): boolean {
  return query.isPending && !query.isFetched;
}
