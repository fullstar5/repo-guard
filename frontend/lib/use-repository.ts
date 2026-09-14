import { useQuery } from "@tanstack/react-query";

import { listRepositories } from "@/lib/api";
import { authMeQueryOptions } from "@/lib/auth-session";
import { repositoryListKey } from "@/lib/query-keys";
import { reconcileFetchedList } from "@/lib/sync-list-cache";

export function useRepository(repositoryId: number) {
  const meQuery = useQuery(authMeQueryOptions);
  const query = useQuery({
    queryKey: repositoryListKey,
    queryFn: async () =>
      reconcileFetchedList(repositoryListKey, await listRepositories()),
    enabled: meQuery.isSuccess && Number.isFinite(repositoryId),
  });

  return {
    repository: query.data?.find((repo) => repo.id === repositoryId),
    isLoading: query.isLoading,
  };
}
