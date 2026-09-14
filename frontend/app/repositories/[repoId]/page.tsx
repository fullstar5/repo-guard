"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { useParams } from "next/navigation";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { GitPullRequest } from "lucide-react";

import { AuthGate } from "@/components/auth-gate";
import { EmptyState, InlineStatus } from "@/components/empty-state";
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
import { authMeQueryOptions } from "@/lib/auth-session";
import { formatRelativeTime } from "@/lib/format";
import { listPullRequests, syncPullRequests } from "@/lib/api";
import { useRepository } from "@/lib/use-repository";

export default function RepositoryPullRequestsPage() {
  const params = useParams<{ repoId: string }>();
  const repositoryId = Number(params.repoId);
  const queryClient = useQueryClient();
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

  const syncButton = (
    <SyncButton
      pending={syncMutation.isPending}
      onClick={() => syncMutation.mutate()}
    />
  );

  return (
    <AuthGate>
      <Breadcrumbs
        items={[
          { label: "Repositories", href: "/" },
          { label: repository?.full_name ?? `Repository ${repositoryId}` },
        ]}
      />

      <PageToolbar title="Pull requests" action={syncButton} />

      {(prsQuery.data?.length ?? 0) > 0 ? (
        <FilterBar>
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder="Search pull requests..."
          />
          <FilterSelect
            value={stateFilter}
            onChange={setStateFilter}
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
        <InlineStatus>Loading pull requests...</InlineStatus>
      ) : prsQuery.isError ? (
        <InlineStatus tone="danger">Failed to load pull requests.</InlineStatus>
      ) : (prsQuery.data?.length ?? 0) === 0 ? (
        <EmptyState
          icon={<GitPullRequest className="size-7 text-[#22d3ee]" aria-hidden="true" />}
          title="No pull requests yet"
          hint="Sync from GitHub to load PRs for this repository."
          actionLabel="Sync"
          onAction={() => syncMutation.mutate()}
          actionPending={syncMutation.isPending}
        />
      ) : filtered.length === 0 ? (
        <InlineStatus>No pull requests match the current filters.</InlineStatus>
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
                  <LeanTableCell>
                    <Link
                      href={`/repositories/${repositoryId}/pull-requests/${pr.id}`}
                      className="text-sm font-medium text-[#fafafa] hover:text-[#67e8f9]"
                    >
                      <span className="mr-2 text-[#a1a1aa]">#{pr.number}</span>
                      {pr.title}
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
