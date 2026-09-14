"use client";

import { SeverityBadge } from "@/components/status-badges";
import type { ReviewFinding, ReviewFindingSeverity } from "@/lib/api";
import { SEVERITY_ORDER } from "@/lib/review-findings";
import { cn } from "@/lib/utils";

export type DiffLine = {
    kind: "hunk" | "add" | "del" | "ctx" | "meta";
    text: string;
    oldLine: number | null;
    newLine: number | null;
};

export type DiffHighlight = {
    startLine: number;
    endLine: number;
    finding: ReviewFinding;
};

function parseHunkHeader(text: string): { oldStart: number; newStart: number } | null {
    const match = text.match(/^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@/);
    if (!match) {
        return null;
    }
    return { oldStart: Number(match[1]), newStart: Number(match[2]) };
}

/**
 * Parse a GitHub unified patch into rows with old/new line numbers.
 * `-` advances old only, `+` advances new only, context advances both.
 */
export function parsePatch(patch: string): DiffLine[] {
    let oldLine = 0;
    let newLine = 0;

    return patch.replace(/\r\n/g, "\n").split("\n").map((text) => {
        if (text.startsWith("@@")) {
            const hunk = parseHunkHeader(text);
            if (hunk) {
                oldLine = hunk.oldStart;
                newLine = hunk.newStart;
            }
            return { kind: "hunk", text, oldLine: null, newLine: null };
        }
        if (text.startsWith("+++") || text.startsWith("---") || text.startsWith("diff ")) {
            return { kind: "meta", text, oldLine: null, newLine: null };
        }
        if (text.startsWith("-")) {
            const line = { kind: "del" as const, text, oldLine, newLine: null };
            oldLine += 1;
            return line;
        }
        if (text.startsWith("+")) {
            const line = { kind: "add" as const, text, oldLine: null, newLine };
            newLine += 1;
            return line;
        }
        const line = { kind: "ctx" as const, text, oldLine, newLine };
        oldLine += 1;
        newLine += 1;
        return line;
    });
}

export function snippetAround(
    patch: string | null,
    startLine: number,
    endLine: number,
    context = 2,
): DiffLine[] {
    if (!patch) {
        return [];
    }
    const min = startLine - context;
    const max = endLine + context;
    return parsePatch(patch).filter((line) => {
        if (line.kind === "hunk" || line.kind === "meta") {
            return false;
        }
        if (line.newLine != null) {
            return line.newLine >= min && line.newLine <= max;
        }
        if (line.oldLine != null && line.kind === "del") {
            return line.oldLine >= min && line.oldLine <= max;
        }
        return false;
    });
}

const LINE_CLASS: Record<DiffLine["kind"], string> = {
    hunk: "bg-[#18181b] text-[#67e8f9]",
    add: "bg-[#14532d]/40 text-[#86efac]",
    del: "bg-[#7f1d1d]/40 text-[#fca5a5]",
    ctx: "text-[#e4e4e7]",
    meta: "text-[#71717a]",
};

const HIGHLIGHT_CLASS: Record<ReviewFindingSeverity, string> = {
    critical: "shadow-[inset_3px_0_0_#ef4444]",
    high: "shadow-[inset_3px_0_0_#f97316]",
    medium: "shadow-[inset_3px_0_0_#eab308]",
    low: "shadow-[inset_3px_0_0_#71717a]",
};

function highlightForLine(
    highlights: DiffHighlight[],
    newLine: number | null,
): DiffHighlight | undefined {
    if (newLine == null) {
        return undefined;
    }
    const hits = highlights.filter(
        (item) => newLine >= item.startLine && newLine <= item.endLine,
    );
    if (hits.length === 0) {
        return undefined;
    }
    return [...hits].sort(
        (left, right) =>
            SEVERITY_ORDER[left.finding.severity] - SEVERITY_ORDER[right.finding.severity],
    )[0];
}

/** Only findings with a start_line can be painted onto the diff. */
export function findingsToHighlights(findings: ReviewFinding[]): DiffHighlight[] {
    return findings
        .filter((finding) => finding.start_line != null)
        .map((finding) => ({
            startLine: finding.start_line as number,
            endLine: finding.end_line ?? (finding.start_line as number),
            finding,
        }));
}

/**
 * Render a unified diff. Highlights must come from the selected job's
 * findings for this file. An empty list means "plain diff", not "pick another job".
 */
export function DiffView({
    patch,
    highlights = [],
}: {
    patch: string | null;
    highlights?: DiffHighlight[];
}) {
    if (!patch) {
        return (
            <p className="text-sm text-[#a1a1aa]">
                No textual diff for this file. It may be binary, empty, or too large for
                GitHub to include a patch.
            </p>
        );
    }

    const lines = parsePatch(patch);

    return (
        <pre className="overflow-x-auto rounded-xl border border-[#3f3f46] bg-[#09090b] text-xs leading-6">
            <code>
                {lines.map((line, index) => {
                    const highlight = highlightForLine(highlights, line.newLine);
                    const comments = highlights.filter(
                        (item) => line.newLine != null && item.endLine === line.newLine,
                    );

                    return (
                        <div key={`${index}-${line.kind}`}>
                            <div
                                id={line.newLine != null ? `L${line.newLine}` : undefined}
                                className={cn(
                                    "grid grid-cols-[3.5rem_3.5rem_1fr]",
                                    LINE_CLASS[line.kind],
                                    highlight ? HIGHLIGHT_CLASS[highlight.finding.severity] : "",
                                )}
                            >
                                <span className="select-none px-2 text-right text-[#52525b]">
                                    {line.oldLine ?? ""}
                                </span>
                                <span className="select-none border-r border-[#27272a] px-2 text-right text-[#52525b]">
                                    {line.newLine ?? ""}
                                </span>
                                <span className="whitespace-pre px-3">
                                    {line.text.length === 0 ? " " : line.text}
                                </span>
                            </div>
                            {comments.map((item) => (
                                <div
                                    key={item.finding.id}
                                    className="border-y border-[#3f3f46] bg-[#18181b] px-4 py-3 text-sm leading-5 text-[#e4e4e7]"
                                >
                                    <div className="mb-1 flex items-center gap-2">
                                        <SeverityBadge severity={item.finding.severity} />
                                        <span className="text-xs text-[#a1a1aa]">
                                            L{item.startLine}
                                            {item.endLine !== item.startLine
                                                ? `–L${item.endLine}`
                                                : ""}
                                        </span>
                                    </div>
                                    <p>{item.finding.summary}</p>
                                    {item.finding.suggestion && (
                                        <p className="mt-1 text-[#a1a1aa]">
                                            {item.finding.suggestion}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    );
                })}
            </code>
        </pre>
    );
}
