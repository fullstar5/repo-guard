import type {
    PullRequestFile,
    ReviewFinding,
    ReviewJob,
    ReviewFindingSeverity,
} from "@/lib/api";




export const SEVERITY_ORDER: Record<ReviewFindingSeverity, number> = {
    critical: 0,
    high: 1,
    medium: 2,
    low: 3,
};


export function pickSelectedReviewJob(
    jobs: ReviewJob[],
    jobIdParam: string | null,
): ReviewJob | undefined {
    // find the job that user ask to view
    if (!jobIdParam) {
        return undefined;
    }
    const jobId = Number(jobIdParam);
    if (!Number.isFinite(jobId)) {
        return undefined;
    }
    return jobs.find((job) => job.id === jobId);
}

/** Latest successful job, else the newest job. Used when the URL has no jobId. */
export function resolveDisplayedReviewJob(
    jobs: ReviewJob[],
    jobIdParam: string | null,
): ReviewJob | undefined {
    const explicit = pickSelectedReviewJob(jobs, jobIdParam);
    if (explicit) {
        return explicit;
    }
    if (jobs.length === 0) {
        return undefined;
    }
    const completed = jobs.filter((job) => job.status === "completed");
    const pool = completed.length > 0 ? completed : jobs;
    return [...pool].sort(
        (left, right) =>
            new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime(),
    )[0];
}


export function resolveFindingFile(
    files: PullRequestFile[],
    finding: ReviewFinding,
): PullRequestFile | undefined {
    // Map a finding onto a synced PR file.
    if (finding.pr_file_id != null) {
        const byId = files.find((file) => file.id === finding.pr_file_id);
        if (byId) {
            return byId;
        }
    }
    if (finding.file_path) {
        return files.find((file) => file.filename === finding.file_path);
    }
    return undefined;
}



export function findingsForFile (
    findings: ReviewFinding[],
    file: PullRequestFile,
): ReviewFinding[] {
    // findings that belong to this file only
    return findings.filter((finding) => {
        if (finding.pr_file_id === file.id) {
            return true;
        }
        return finding.file_path === file.filename;
    });
}



/** Human-readable location, e.g. src/a.ts:12-14. Display only. */
export function findingLocationLabel(finding: ReviewFinding): string {
    const path = finding.file_path ?? "Unknown file";
    if (finding.start_line == null) {
        return path;
    }
    if (finding.end_line == null || finding.end_line === finding.start_line) {
        return `${path}:${finding.start_line}`;
    }
    return `${path}:${finding.start_line}-${finding.end_line}`;
}


/**
 * Deep link to the matching file + this job + line hash.
 * Returns null when the file cannot be resolved, so the UI does not
 * send the user to a different file.
 */
export function findingFileHref(
    repositoryId: number,
    pullRequestId: number,
    files: PullRequestFile[],
    finding: ReviewFinding,
    jobId: number,
): string | null {
    const file = resolveFindingFile(files, finding);
    if (!file) {
        return null;
    }
    const hash = finding.start_line != null ? `#L${finding.start_line}` : "";
    return `/repositories/${repositoryId}/pull-requests/${pullRequestId}/files/${file.id}?jobId=${jobId}${hash}`;
}