import { useQuery } from "@tanstack/react-query";

import { listRepositories } from "@/lib/api";
import { authMeQueryOptions } from "@/lib/auth-session";

export function useRepository(repositoryId: number) {
  const meQuery = useQuery(authMeQueryOptions);
  const query = useQuery({
    queryKey: ["repositories"],
    queryFn: listRepositories,
    enabled: meQuery.isSuccess && Number.isFinite(repositoryId),
  });

  return {
    repository: query.data?.find((repo) => repo.id === repositoryId),
    isLoading: query.isLoading,
  };
}
