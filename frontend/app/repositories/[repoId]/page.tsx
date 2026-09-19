"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitPullRequest } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { EmptyState } from "@/components/empty-state";
import { FilterEmpty, QueryError, TableSkeleton } from "@/components/feedback";
import {
  Breadcrumbs,
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
import { PullRequestStateBadge } from "@/components/status-badges";
import { SyncButton } from "@/components/sync-button";
import { useToast } from "@/components/toast";
import { authMeQueryOptions } from "@/lib/auth-session";
import { formatRelativeTime } from "@/lib/format";
import { listPullRequests, syncPullRequests } from "@/lib/api";
import { useRepository } from "@/lib/use-repository";

export default function RepositoryPullRequestsPage() {
  const params = useParams<{ repoId: string }>();
  const repositoryId = Number(params.repoId);
  const queryClient = useQueryClient();
  const toast = useToast();
  const [search, setSearch] = useState("");
  const [stateFilter, setStateFilter] = useState("all");

  const meQuery = useQuery(authMeQueryOptions);
  const { repository } = useRepository(repositoryId);

  const prsQuery = useQuery({
    queryKey: ["repositories", repositoryId, "pull-requests"],
    queryFn: () => listPullRequests(repositoryId),
    enabled: meQuery.isSuccess && Number.isFinite(repositoryId),
  });

  const syncMutation = useMutation({
    mutationFn: () => syncPullRequests(repositoryId),
    onSuccess: (items) => {
      queryClient.setQueryData(
        ["repositories", repositoryId, "pull-requests"],
        items,
      );
      toast({ tone: "success", message: "Pull requests updated." });
    },
    onError: () => {
      toast({ tone: "danger", message: "Couldn't sync pull requests." });
    },
  });

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (prsQuery.data ?? []).filter((pr) => {
      if (stateFilter === "open" && (pr.is_draft || pr.state.toLowerCase() !== "open")) {
        return false;
      }
      if (stateFilter === "closed" && pr.state.toLowerCase() === "open") {
        return false;
      }
      if (stateFilter === "draft" && !pr.is_draft) {
        return false;
      }
      if (!query) {
        return true;
      }
      return (
        pr.title.toLowerCase().includes(query) ||
        `#${pr.number}`.includes(query) ||
        (pr.author_login ?? "").toLowerCase().includes(query)
      );
    });
  }, [prsQuery.data, search, stateFilter]);

  const total = prsQuery.data?.length ?? 0;
  const toolbarMeta =
    total === 0
      ? undefined
      : filtered.length === total
        ? `${total} ${total === 1 ? "pull request" : "pull requests"}`
        : `${filtered.length} of ${total} pull requests`;

  return (
    <AuthGate>
      <Breadcrumbs
        items={[
          { label: "Repositories", href: "/" },
          { label: repository?.full_name ?? `Repository ${repositoryId}` },
        ]}
      />

      <PageToolbar
        title="Pull requests"
        meta={toolbarMeta}
        action={
          <SyncButton
            pending={syncMutation.isPending}
            onClick={() => syncMutation.mutate()}
            aria-label={syncMutation.isPending ? "Syncing pull requests" : "Sync pull requests"}
          />
        }
      />

      {total > 0 ? (
        <FilterBar>
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search pull requests..."
          />
          <FilterSelect
            value={stateFilter}
            onChange={setStateFilter}
            aria-label="Filter by pull request state"
            options={[
              { value: "all", label: "All" },
              { value: "open", label: "Open" },
              { value: "closed", label: "Closed" },
              { value: "draft", label: "Draft" },
            ]}
          />
        </FilterBar>
      ) : null}

      {prsQuery.isLoading ? (
        <TableSkeleton />
      ) : prsQuery.isError ? (
        <QueryError
          message="Failed to load pull requests."
          onRetry={() => void prsQuery.refetch()}
        />
      ) : total === 0 ? (
        <EmptyState
          icon={<GitPullRequest className="size-7 text-[#22d3ee]" aria-hidden="true" />}
          title="No pull requests yet"
          hint="Sync from GitHub to load PRs for this repository."
          actionLabel="Sync"
          onAction={() => syncMutation.mutate()}
          actionPending={syncMutation.isPending}
        />
      ) : filtered.length === 0 ? (
        <FilterEmpty
          title="No matching pull requests"
          hint="Try a different search or state filter."
        />
      ) : (
        <LeanTable>
          <Table>
            <LeanTableHeader>
              <LeanTableRow>
                <LeanTableHead>Title</LeanTableHead>
                <LeanTableHead>State</LeanTableHead>
                <LeanTableHead className="text-right">Updated</LeanTableHead>
              </LeanTableRow>
            </LeanTableHeader>
            <TableBody>
              {filtered.map((pr) => (
                <LeanTableRow key={pr.id}>
                  <LeanTableCell className="max-w-[36rem]">
                    <Link
                      href={`/repositories/${repositoryId}/pull-requests/${pr.id}`}
                      title={`#${pr.number} ${pr.title}`}
                      className="flex min-w-0 items-baseline text-sm font-medium text-[#fafafa] hover:text-[#67e8f9] focus-visible:text-[#67e8f9] focus-visible:ring-2 focus-visible:ring-[#22d3ee]/70 focus-visible:outline-none"
                    >
                      <span className="mr-2 shrink-0 text-[#a1a1aa]">#{pr.number}</span>
                      <span className="truncate">{pr.title}</span>
                    </Link>
                  </LeanTableCell>
                  <LeanTableCell>
                    <PullRequestStateBadge state={pr.state} isDraft={pr.is_draft} />
                  </LeanTableCell>
                  <LeanTableCell className="text-right text-[#a1a1aa]">
                    {formatRelativeTime(pr.github_updated_at)}
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
