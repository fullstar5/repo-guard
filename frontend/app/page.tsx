"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { BookMarked } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { EmptyState } from "@/components/empty-state";
import { FilterEmpty, QueryError, TableSkeleton } from "@/components/feedback";
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
import { SyncButton } from "@/components/sync-button";
import { useToast } from "@/components/toast";
import { authMeQueryOptions } from "@/lib/auth-session";
import { formatRelativeTime } from "@/lib/format";
import { listRepositories, syncRepositories } from "@/lib/api";

export default function HomePage() {
  const queryClient = useQueryClient();
  const toast = useToast();
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
      toast({ tone: "success", message: "Repositories updated." });
    },
    onError: () => {
      toast({ tone: "danger", message: "Couldn't sync repositories." });
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

  const total = reposQuery.data?.length ?? 0;
  const toolbarMeta =
    total === 0
      ? undefined
      : filtered.length === total
        ? `${total} ${total === 1 ? "repository" : "repositories"}`
        : `${filtered.length} of ${total} repositories`;

  return (
    <AuthGate>
      <PageToolbar
        title="Repositories"
        meta={toolbarMeta}
        action={
          <SyncButton
            pending={syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
            aria-label={syncMutation.isPending ? "Syncing repositories" : "Sync repositories"}
          />
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
          aria-label="Filter by visibility"
          options={[
            { value: "all", label: "All visibility" },
            { value: "public", label: "Public" },
            { value: "private", label: "Private" },
          ]}
        />
      </FilterBar>

      {reposQuery.isLoading ? (
        <TableSkeleton />
      ) : reposQuery.isError ? (
        <QueryError
          message="Failed to load repositories."
          onRetry={() => void reposQuery.refetch()}
        />
      ) : total === 0 ? (
        <EmptyState
          icon={<BookMarked className="size-7 text-[#22d3ee]" aria-hidden="true" />}
          title="No repositories yet"
          hint="Sync from GitHub to load repositories for this workspace."
          actionLabel="Sync"
          onAction={() => syncMutation.mutate()}
          actionPending={syncMutation.isPending}
        />
      ) : filtered.length === 0 ? (
        <FilterEmpty
          title="No matching repositories"
          hint="Try a different search or visibility filter."
        />
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
                  <LeanTableCell className="max-w-[36rem]">
                    <Link
                      href={`/repositories/${repo.id}`}
                      title={repo.full_name}
                      className="flex min-w-0 items-center gap-3 font-medium text-[#fafafa] hover:text-[#67e8f9] focus-visible:text-[#67e8f9] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
                    >
                      <BookMarked className="size-4 shrink-0 text-[#a1a1aa]" aria-hidden="true" />
                      <span className="truncate">{repo.full_name}</span>
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
