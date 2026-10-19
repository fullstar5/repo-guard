import re

from agent_experiments.agent_day4.related import is_ignored_path

MAX_PATHS_PER_SPECIALIST = 4
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_FINDINGS_CONTRACT = (
    "Return one JSON object and no markdown fence:\n"
    '{"summary":"short overall summary","findings":[{"severity":"low|medium|high|critical",'
    '"summary":"actionable issue in your specialty",'
    '"file_path":"a path from the user message or null",'
    '"start_line":10,"end_line":12,"suggestion":"concrete fix or null"}]}\n'
    "Rules:\n"
    "- file_path and line numbers must come from the files in the user message.\n"
    "- Do not mention a path that was not provided. Do not invent file contents.\n"
    "- Report only defects a reviewer would ask the author to change.\n"
    "- Do not report formatting, comments, rename-only edits, or vague style preferences.\n"
    "- If this slice has no issue in your specialty, findings is an empty array.\n"
    "- Start summary with the specific risk, such as \"SQL injection:\" or \"missing timeout:\"."
)

SPECIALIST_PROMPTS: dict[str, str] = {
    "security": (
        "You are the CodeGuard security specialist. You review only the files in the "
        "user message. You have no repository access and no tools.\n"
        "Look for security defects, not only authentication and permission checks:\n"
        "- Authentication and sessions: weak password storage, missing credential "
        "rotation, session fixation, tokens in URLs, cookies without Secure/HttpOnly/"
        "SameSite, authentication bypass.\n"
        "- Authorization: missing ownership checks, IDOR, privilege escalation, "
        "mass assignment, trusting client-supplied roles or tenant ids.\n"
        "- Injection: SQL, command, LDAP, template, header, log, and path injection. "
        "Unsafe deserialization of pickle, YAML, or similar formats.\n"
        "- Web: XSS, CSRF, SSRF, open redirects, path traversal, zip slip, CORS that "
        "reflects arbitrary origins with credentials.\n"
        "- Secrets and data exposure: keys or passwords in code, sensitive data in "
        "logs or error text, PII in query strings, debug endpoints left enabled.\n"
        "- Cryptography: hardcoded keys, broken algorithms, disabled TLS verification, "
        "ECB mode, secrets compared with a non-constant-time check when the code shows it.\n"
        "Ignore performance, naming, and product formatting.\n"
        + _FINDINGS_CONTRACT
    ),
    "correctness": (
        "You are the CodeGuard correctness specialist. You review only the files in "
        "the user message. You have no repository access and no tools.\n"
        "Look for behavior that is wrong on inputs the code claims to handle:\n"
        "- Logic: inverted conditions, unreachable branches, off-by-one, wrong "
        "operator, stale comparisons, mishandled boolean flags.\n"
        "- Empty and missing data: null, undefined, empty collections, missing keys, "
        "optional values used without a check.\n"
        "- Errors: swallowed exceptions, the wrong exception type, partial writes "
        "left in place, error paths that return success.\n"
        "- State: illegal transitions, updates applied twice, lost updates, "
        "use of a value after it was cleared or closed.\n"
        "- Concurrency: check-then-act races, shared mutable state, missing locking "
        "where the diff shows concurrent callers, deadlocks.\n"
        "- Boundaries: overflow, encoding, time zones, inclusive versus exclusive ranges.\n"
        "A passing happy path is not enough when the diff shows a broken edge. "
        "Do not report security policy or performance unless the bug is simply wrong output.\n"
        + _FINDINGS_CONTRACT
    ),
    "performance": (
        "You are the CodeGuard performance specialist. You review only the files in "
        "the user message. You have no repository access and no tools.\n"
        "Look for work that gets much more expensive as data or traffic grows:\n"
        "- Database and I/O: queries inside loops, N+1 fetches, loading an entire "
        "table, missing pagination, repeated identical requests.\n"
        "- Complexity: accidental quadratic or worse scans, repeated full copies of "
        "large structures, unbounded in-memory accumulation.\n"
        "- Hot paths: blocking network or disk calls on a request path, chatty "
        "round trips, huge payloads, work repeated per item when once is enough.\n"
        "- Caching: a clear repeated computation with no reuse, or a cache key that "
        "cannot hit. Do not demand a cache without evidence of repeated work.\n"
        "- UI: rendering large lists without a bound, effects that refetch on every "
        "render when the diff shows that loop.\n"
        "Do not flag micro-optimizations, style, or a missing index you cannot see "
        "in the provided code.\n"
        + _FINDINGS_CONTRACT
    ),
    "reliability": (
        "You are the CodeGuard reliability specialist. You review only the files in "
        "the user message. You have no repository access and no tools.\n"
        "Look for failures that leave the system stuck, duplicated, or inconsistent:\n"
        "- Network and jobs: calls with no timeout, retries with no backoff, retries "
        "of a non-idempotent write, jobs that can run twice and double-apply.\n"
        "- Partial failure: a multi-step update that can stop halfway, a transaction "
        "that does not cover the writes that must succeed together, errors ignored "
        "so a later step runs on bad state.\n"
        "- Resources: connections, files, locks, or subscriptions opened and not "
        "released on the error path.\n"
        "- Queues and workers: poison messages retried forever, no dead-letter or "
        "attempt limit where the code shows a retry loop, shutdown that drops in-flight work "
        "without a defined outcome.\n"
        "- External dependency failure: assuming a downstream call always succeeds, "
        "or treating a timeout as an empty success.\n"
        "Do not repeat a pure logic bug that does not involve failure, recovery, or resources.\n"
        + _FINDINGS_CONTRACT
    ),
    "contract": (
        "You are the CodeGuard API and data-contract specialist. You review only the "
        "files in the user message. You have no repository access and no tools.\n"
        "Look for changes that break callers, stored data, or downstream consumers:\n"
        "- APIs: removed or renamed fields, changed types, changed status codes, "
        "stricter validation without a compatible path, error bodies that changed shape.\n"
        "- Input: external input accepted without the checks the rest of the code "
        "relies on, silent truncation, mixed units, timezone-naive values written as if they were absolute.\n"
        "- Schema and migrations: dropping a column that is still read, a NOT NULL "
        "column with no default or backfill, a migration that rewrites a large table "
        "in one locking step when the diff shows that statement.\n"
        "- Compatibility: events, webhooks, or serialized payloads whose fields "
        "changed while older producers or consumers are still in the diff.\n"
        "- Persistence: lost updates, writes that can overwrite a newer row, unique "
        "constraints the code can violate.\n"
        "Do not review visual style or generic naming.\n"
        + _FINDINGS_CONTRACT
    ),
    "maintainability": (
        "You are the CodeGuard change-risk specialist. You review only the files in "
        "the user message. You have no repository access and no tools.\n"
        "Look only for structure that will make the next change incorrect:\n"
        "- Divergent copies: the diff updates one copy of a rule and leaves another "
        "copy with the old behavior.\n"
        "- Misleading code: a name, flag, or comment in the diff contradicts the "
        "behavior of the changed lines and would cause a wrong edit later.\n"
        "- Dead or broken control flow: a branch that cannot run, or an error path "
        "that drops a check the success path has.\n"
        "- Hidden coupling: a new caller depends on an incidental order or a magic "
        "value that the diff does not define in one place.\n"
        "Do not report formatting, import order, comment wording, or a preference "
        "to split a function. If the changed code is simply long but consistent, "
        "return an empty findings array.\n"
        + _FINDINGS_CONTRACT
    ),
}

SPECIALIST_TOOL_NAMES = {
    "ask_security_specialist": "security",
    "ask_correctness_specialist": "correctness",
    "ask_performance_specialist": "performance",
    "ask_reliability_specialist": "reliability",
    "ask_contract_specialist": "contract",
    "ask_maintainability_specialist": "maintainability",
}


def specialist_tools() -> list[dict[str, object]]:
    """Build the orchestrator tools that open a specialist conversation.

    Returns:
        One strict function schema per specialty. Each call sends only the paths
        the orchestrator lists.
    """
    descriptions = {
        "ask_security_specialist": (
            "Ask the security specialist to review paths already read. "
            "Covers authentication, authorization, injection, web attacks, secrets, "
            "and cryptography. Send only the paths relevant to that review."
        ),
        "ask_correctness_specialist": (
            "Ask the correctness specialist to review paths already read. "
            "Covers logic, empty data, error handling, state, concurrency, and boundaries."
        ),
        "ask_performance_specialist": (
            "Ask the performance specialist to review paths already read. "
            "Covers N+1 queries, unbounded work, hot paths, and repeated expensive calls."
        ),
        "ask_reliability_specialist": (
            "Ask the reliability specialist to review paths already read. "
            "Covers timeouts, retries, idempotency, partial failure, and resource leaks."
        ),
        "ask_contract_specialist": (
            "Ask the contract specialist to review paths already read. "
            "Covers breaking API changes, validation, migrations, and persisted data."
        ),
        "ask_maintainability_specialist": (
            "Ask the change-risk specialist to review paths already read. "
            "Covers divergent copies and misleading control flow. Not for style."
        ),
    }
    tools: list[dict[str, object]] = []
    for name, description in descriptions.items():
        tools.append(
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "strict": True,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "paths": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Paths already returned by get_file_content.",
                            },
                            "focus": {
                                "type": "string",
                                "description": "What this specialist should examine in those paths.",
                            },
                        },
                        "required": ["paths", "focus"],
                        "additionalProperties": False,
                    },
                },
            }
        )
    return tools


FINISH_REVIEW: dict[str, object] = {
    "type": "function",
    "function": {
        "name": "finish_review",
        "description": (
            "Stop after the assigned specialists have returned. "
            "Merges their findings and does not accept new issues."
        ),
        "strict": True,
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
            "additionalProperties": False,
        },
    },
}


def slice_read_files(
    read_files: dict[str, dict[str, object]],
    paths: object,
) -> dict[str, object]:
    """Select only the requested files that this review has already read.

    The patch and source text are the copies already stored by get_file_content.
    That read already limits each field to 8000 characters.

    Args:
        read_files: Bodies saved after successful reads.
        paths: The specialist tool's ``paths`` argument.

    Returns:
        ``files`` for the specialist, or an error naming what must be fixed.
    """
    if not isinstance(paths, list) or not paths:
        return {"error": "paths must be a non-empty list."}
    if len(paths) > MAX_PATHS_PER_SPECIALIST:
        return {"error": f"Send at most {MAX_PATHS_PER_SPECIALIST} paths to one specialist."}

    files: list[dict[str, object]] = []
    for path in paths:
        if not isinstance(path, str) or not path.strip():
            return {"error": "Each path must be a non-empty string."}
        path = path.strip()
        if is_ignored_path(path):
            return {"error": f"{path} is ignored and cannot be sent to a specialist."}
        saved = read_files.get(path)
        if not isinstance(saved, dict) or "error" in saved:
            return {"error": f"Read {path} with get_file_content before assigning it."}
        files.append(
            {
                "path": path,
                "status": saved.get("status"),
                "patch": saved.get("patch"),
                "source_text": saved.get("source_text"),
            }
        )
    return {"files": files}


def aggregate_findings(reports: list[dict[str, object]]) -> dict[str, object]:
    """Merge specialist findings without adding a new issue.

    Two findings merge when they name the same file, their line ranges overlap,
    and at least 60 percent of the shorter summary's words appear in the other.
    The kept item uses the higher severity and the longer suggestion.

    Args:
        reports: One dictionary per specialist call, each with ``findings``.

    Returns:
        A summary and the deduplicated findings, highest severity first.
    """
    merged: list[dict[str, object]] = []
    for report in reports:
        findings = report.get("findings")
        if not isinstance(findings, list):
            continue
        for finding in findings:
            if not isinstance(finding, dict):
                continue
            partner = None
            for item in merged:
                if item.get("file_path") != finding.get("file_path"):
                    continue
                left_start = item.get("start_line")
                right_start = finding.get("start_line")
                if isinstance(left_start, int) and isinstance(right_start, int):
                    left_end = item.get("end_line")
                    right_end = finding.get("end_line")
                    left_end = left_end if isinstance(left_end, int) else left_start
                    right_end = right_end if isinstance(right_end, int) else right_start
                    if not (left_start <= right_end and right_start <= left_end):
                        continue
                left_tokens = {
                    token
                    for token in re.findall(r"[a-z0-9]+", str(item.get("summary") or "").lower())
                    if len(token) >= 3
                }
                right_tokens = {
                    token
                    for token in re.findall(r"[a-z0-9]+", str(finding.get("summary") or "").lower())
                    if len(token) >= 3
                }
                if not left_tokens or not right_tokens:
                    continue
                shared = left_tokens & right_tokens
                if len(shared) / min(len(left_tokens), len(right_tokens)) >= 0.6:
                    partner = item
                    break
            if partner is None:
                merged.append(dict(finding))
                continue
            current_rank = _SEVERITY_RANK.get(str(partner.get("severity")), 2)
            incoming_rank = _SEVERITY_RANK.get(str(finding.get("severity")), 2)
            if incoming_rank < current_rank:
                partner["severity"] = finding.get("severity")
                partner["summary"] = finding.get("summary")
            incoming_suggestion = finding.get("suggestion")
            current_suggestion = partner.get("suggestion")
            if isinstance(incoming_suggestion, str) and (
                not isinstance(current_suggestion, str)
                or len(incoming_suggestion) > len(current_suggestion)
            ):
                partner["suggestion"] = incoming_suggestion
    merged.sort(
        key=lambda item: (
            _SEVERITY_RANK.get(str(item.get("severity")), 2),
            str(item.get("file_path") or ""),
            item.get("start_line") if isinstance(item.get("start_line"), int) else 0,
        )
    )
    specialists = sorted(
        {str(report.get("specialist")) for report in reports if report.get("specialist")}
    )
    if not merged:
        summary = "No specialist reported an issue."
    else:
        summary = f"Merged {len(merged)} findings from {', '.join(specialists)}."
    return {"summary": summary, "findings": merged}
