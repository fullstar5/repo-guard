"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked, RefreshCw } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { EmptyState, InlineStatus } from "@/components/empty-state";
import {
  FilterBar,
  FilterSelect,
  PageToolbar,
  SearchInput,
} from "@/components/page-chrome";
import {
  LeanTable,
  LeanTableCell,
  LeanTableHead,
  LeanTableHeader,
  LeanTableRow,
  Table,
  TableBody,
} from "@/components/lean-table";
import { VisibilityBadge } from "@/components/status-badges";
import { Button } from "@/components/ui/button";
import { authMeQueryOptions } from "@/lib/auth-session";
import { formatRelativeTime } from "@/lib/format";
import { listRepositories, syncRepositories } from "@/lib/api";

export default function HomePage() {
  const queryClient = useQueryClient();
  const meQuery = useQuery(authMeQueryOptions);
  const [search, setSearch] = useState("");
  const [visibility, setVisibility] = useState("all");

  const reposQuery = useQuery({
    queryKey: ["repositories"],
    queryFn: listRepositories,
    enabled: meQuery.isSuccess,
  });

  const syncMutation = useMutation({
    mutationFn: syncRepositories,
    onSuccess: (items) => {
      queryClient.setQueryData(["repositories"], items);
    },
  });

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (reposQuery.data ?? []).filter((repo) => {
      if (visibility === "private" && !repo.private) {
        return false;
      }
      if (visibility === "public" && repo.private) {
        return false;
      }
      if (!query) {
        return true;
      }
      return repo.full_name.toLowerCase().includes(query);
    });
  }, [reposQuery.data, search, visibility]);

  return (
    <AuthGate>
      <PageToolbar
        title="Repositories"
        action={
          <Button
            variant="outline"
            onClick={() => syncMutation.mutate()}
            disabled={syncMutation.isPending}
          >
            <RefreshCw className="size-4" aria-hidden="true" />
            {syncMutation.isPending ? "Syncing..." : "Sync"}
          </Button>
        }
      />

      <FilterBar>
        <SearchInput
          value={search}
          onChange={setSearch}
          placeholder="Search repositories..."
        />
        <FilterSelect
          value={visibility}
          onChange={setVisibility}
          options={[
            { value: "all", label: "All visibility" },
            { value: "public", label: "Public" },
            { value: "private", label: "Private" },
          ]}
        />
      </FilterBar>

      {reposQuery.isLoading ? (
        <InlineStatus>Loading repositories...</InlineStatus>
      ) : reposQuery.isError ? (
        <InlineStatus tone="danger">Failed to load repositories.</InlineStatus>
      ) : (reposQuery.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<BookMarked className="size-7 text-[#22d3ee]" aria-hidden="true" />}
          title="No repositories yet"
          hint="Sync from GitHub to load repositories for this workspace."
          actionLabel="Sync"
          onAction={() => syncMutation.mutate()}
          actionPending={syncMutation.isPending}
        />
      ) : filtered.length === 0 ? (
        <InlineStatus>No repositories match the current filters.</InlineStatus>
      ) : (
        <LeanTable>
          <Table>
            <LeanTableHeader>
              <LeanTableRow>
                <LeanTableHead>Repository</LeanTableHead>
                <LeanTableHead>Visibility</LeanTableHead>
                <LeanTableHead className="text-right">Updated</LeanTableHead>
              </LeanTableRow>
            </LeanTableHeader>
            <TableBody>
              {filtered.map((repo) => (
                <LeanTableRow key={repo.id}>
                  <LeanTableCell>
                    <Link
                      href={`/repositories/${repo.id}`}
                      className="flex items-center gap-3 font-medium text-[#fafafa] hover:text-[#67e8f9]"
                    >
                      <BookMarked className="size-4 shrink-0 text-[#a1a1aa]" aria-hidden="true" />
                      {repo.full_name}
                    </Link>
                  </LeanTableCell>
                  <LeanTableCell>
                    <VisibilityBadge isPrivate={repo.private} />
                  </LeanTableCell>
                  <LeanTableCell className="text-right text-[#a1a1aa]">
                    {formatRelativeTime(repo.updated_at)}
                  </LeanTableCell>
                </LeanTableRow>
              ))}
            </TableBody>
          </Table>
        </LeanTable>
      )}
    </AuthGate>
  );
}
