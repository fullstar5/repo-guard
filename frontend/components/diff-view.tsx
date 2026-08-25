"use client";

import type { ReviewFinding, ReviewFindingSeverity } from "@/lib/api";
import { SeverityBadge } from "@/components/review-findings";
import { SEVERITY_ORDER } from "@/lib/review-findings";

type DiffLine = {
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
function parsePatch(patch: string): DiffLine[] {
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

const LINE_CLASS: Record<DiffLine["kind"], string> = {
    hunk: "bg-blue-50 text-blue-800",
    add: "bg-emerald-50 text-emerald-800",
    del: "bg-red-50 text-red-800",
    ctx: "text-zinc-800",
    meta: "text-zinc-500",
};

const HIGHLIGHT_CLASS: Record<ReviewFindingSeverity, string> = {
    critical: "outline outline-2 outline-red-500",
    high: "outline outline-2 outline-orange-500",
    medium: "outline outline-2 outline-amber-400",
    low: "outline outline-2 outline-zinc-400",
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
            <p className="text-sm text-zinc-500">
                No textual diff for this file. It may be binary, empty, or too large for
                GitHub to include a patch.
            </p>
        );
    }

    const lines = parsePatch(patch);

    return (
        <pre className="overflow-x-auto rounded-lg border bg-zinc-50 text-xs leading-6">
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
                                className={`grid grid-cols-[3.5rem_3.5rem_1fr] ${LINE_CLASS[line.kind]} ${
                                    highlight ? HIGHLIGHT_CLASS[highlight.finding.severity] : ""
                                }`}
                            >
                                <span className="select-none px-2 text-right text-zinc-400">
                                    {line.oldLine ?? ""}
                                </span>
                                <span className="select-none border-r px-2 text-right text-zinc-400">
                                    {line.newLine ?? ""}
                                </span>
                                <span className="whitespace-pre px-3">
                                    {line.text.length === 0 ? " " : line.text}
                                </span>
                            </div>
                            {comments.map((item) => (
                                <div
                                    key={item.finding.id}
                                    className="border-t bg-white px-4 py-3 text-sm leading-5 text-zinc-800"
                                >
                                    <div className="mb-1 flex items-center gap-2">
                                        <SeverityBadge severity={item.finding.severity} />
                                        <span className="text-xs text-zinc-500">
                                            L{item.startLine}
                                            {item.endLine !== item.startLine
                                                ? `–L${item.endLine}`
                                                : ""}
                                        </span>
                                    </div>
                                    <p>{item.finding.summary}</p>
                                    {item.finding.suggestion && (
                                        <p className="mt-1 text-zinc-600">
                                            Suggestion: {item.finding.suggestion}
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