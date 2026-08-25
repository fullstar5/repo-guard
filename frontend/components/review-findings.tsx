"use client";

import Link from "next/link";
import { useMemo, useState } from "react";

import {
    Card,
    CardContent,
    CardDescription,
    CardHeader,
    CardTitle,
} from "@/components/ui/card";
import type {
    PullRequestFile,
    ReviewFinding,
    ReviewFindingSeverity,
    ReviewJob,
} from "@/lib/api";
import {
    SEVERITY_ORDER,
    findingFileHref,
    findingLocationLabel,
} from "@/lib/review-findings";

const SEVERITY_FILTERS: Array<ReviewFindingSeverity | "all"> = [
    "all",
    "critical",
    "high",
    "medium",
    "low",
];

const SEVERITY_CLASS: Record<ReviewFindingSeverity, string> = {
    critical: "bg-red-100 text-red-800",
    high: "bg-orange-100 text-orange-800",
    medium: "bg-amber-100 text-amber-800",
    low: "bg-zinc-200 text-zinc-700",
};

export function SeverityBadge({ severity }: { severity: ReviewFindingSeverity }) {
    return (
        <span
            className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium capitalize ${SEVERITY_CLASS[severity]}`}
        >
            {severity}
        </span>
    );
}

/**
 * Read one review job: summary + filterable findings.
 * The parent must pass the job the user selected. This component
 * never picks a different job.
 */
export function ReviewFindingsPanel({
    job,
    files,
    repositoryId,
    pullRequestId,
}: {
    job: ReviewJob;
    files: PullRequestFile[];
    repositoryId: number;
    pullRequestId: number;
}) {
    const [severity, setSeverity] = useState<ReviewFindingSeverity | "all">("all");
    const [filePath, setFilePath] = useState("all");

    const fileOptions = useMemo(() => {
        const paths = new Set<string>();
        for (const finding of job.findings) {
            if (finding.file_path) {
                paths.add(finding.file_path);
            }
        }
        return [...paths].sort();
    }, [job.findings]);

    const filtered = useMemo(() => {
        return [...job.findings]
            .filter((finding) => severity === "all" || finding.severity === severity)
            .filter((finding) => filePath === "all" || finding.file_path === filePath)
            .sort((left, right) => {
                const bySeverity =
                    SEVERITY_ORDER[left.severity] - SEVERITY_ORDER[right.severity];
                return bySeverity !== 0 ? bySeverity : left.id - right.id;
            });
    }, [job.findings, severity, filePath]);

    if (job.status === "pending" || job.status === "processing") {
        return (
            <p className="text-sm text-zinc-500">
                Review is still running. Summary and findings will appear when this
                job completes.
            </p>
        );
    }

    if (job.status === "failed") {
        return (
            <p className="text-sm text-red-600">
                {job.error_message ?? "Review job failed."}
            </p>
        );
    }

    return (
        <div className="flex flex-col gap-4">
            <Card>
                <CardHeader>
                    <CardTitle>Summary</CardTitle>
                    <CardDescription>
                        Job #{job.id} · {job.model_name} · {job.findings.length} finding
                        {job.findings.length === 1 ? "" : "s"}
                    </CardDescription>
                </CardHeader>
                <CardContent>
                    <p className="whitespace-pre-wrap text-sm text-zinc-800">
                        {job.result_summary?.trim() || "No summary returned."}
                    </p>
                </CardContent>
            </Card>

            <div className="flex flex-wrap items-center gap-3">
                <label className="flex items-center gap-2 text-sm text-zinc-600">
                    Severity
                    <select
                        className="rounded-md border bg-white px-2 py-1 text-sm"
                        value={severity}
                        onChange={(event) => {
                            setSeverity(event.target.value as ReviewFindingSeverity | "all");
                        }}
                    >
                        {SEVERITY_FILTERS.map((value) => (
                            <option key={value} value={value}>
                                {value}
                            </option>
                        ))}
                    </select>
                </label>
                <label className="flex items-center gap-2 text-sm text-zinc-600">
                    File
                    <select
                        className="max-w-xs rounded-md border bg-white px-2 py-1 text-sm"
                        value={filePath}
                        onChange={(event) => setFilePath(event.target.value)}
                    >
                        <option value="all">all</option>
                        {fileOptions.map((path) => (
                            <option key={path} value={path}>
                                {path}
                            </option>
                        ))}
                    </select>
                </label>
                <span className="text-sm text-zinc-500">{filtered.length} shown</span>
            </div>

            {filtered.length === 0 ? (
                <p className="text-sm text-zinc-500">
                    No findings match the current filters.
                </p>
            ) : (
                <ul className="flex flex-col gap-3">
                    {filtered.map((finding) => (
                        <FindingCard
                            key={finding.id}
                            finding={finding}
                            href={findingFileHref(
                                repositoryId,
                                pullRequestId,
                                files,
                                finding,
                                job.id,
                            )}
                        />
                    ))}
                </ul>
            )}
        </div>
    );
}

function FindingCard({
    finding,
    href,
}: {
    finding: ReviewFinding;
    href: string | null;
}) {
    const location = findingLocationLabel(finding);

    return (
        <li className="rounded-xl border bg-white p-4">
            <div className="mb-2 flex flex-wrap items-center gap-2">
                <SeverityBadge severity={finding.severity} />
                {href ? (
                    <Link href={href} className="text-sm font-medium hover:underline">
                        {location}
                    </Link>
                ) : (
                    <span className="text-sm font-medium text-zinc-700">{location}</span>
                )}
            </div>
            <p className="text-sm text-zinc-800">{finding.summary}</p>
            {finding.suggestion && (
                <p className="mt-2 text-sm text-zinc-600">
                    Suggestion: {finding.suggestion}
                </p>
            )}
        </li>
    );
}