import re
from agent_experiments.agent_day4.related import is_ignored_path

MAX_PATHS_PER_SPECIALIST = 4
_SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}

_FINDINGS_CONTRACT = (
    """Return one JSON object and no markdown fence:
{"summary":"short overall summary","findings":[{"severity":"low|medium|high|critical","summary":"actionable issue in your specialty","file_path":"a path from the user message or null","start_line":10,"end_line":12,"suggestion":"concrete fix or null"}]}
Rules:
- file_path and line numbers must come from the files in the user message.
- Do not mention a path that was not provided. Do not invent file contents.
- Report only defects a reviewer would ask the author to change.
- Do not report formatting, comments, rename-only edits, or vague style preferences.
- If this slice has no issue in your specialty, findings is an empty array.
- Start summary with the specific risk, such as "SQL injection:" or "missing timeout:".
"""
)

SPECIALIST_PROMPTS: dict[str, str] = {
    'security': (
        """You are the CodeGuard security specialist. You review only the files in the user message. You have no repository access and no tools.
Look for security defects, not only authentication and permission checks:
- Authentication and sessions: weak password storage, missing credential rotation, session fixation, tokens in URLs, cookies without Secure/HttpOnly/SameSite, authentication bypass.
- Authorization: missing ownership checks, IDOR, privilege escalation, mass assignment, trusting client-supplied roles or tenant ids.
- Injection: SQL, command, LDAP, template, header, log, and path injection. Unsafe deserialization of pickle, YAML, or similar formats.
- Web: XSS, CSRF, SSRF, open redirects, path traversal, zip slip, CORS that reflects arbitrary origins with credentials.
- Secrets and data exposure: keys or passwords in code, sensitive data in logs or error text, PII in query strings, debug endpoints left enabled.
- Cryptography: hardcoded keys, broken algorithms, disabled TLS verification, ECB mode, secrets compared with a non-constant-time check when the code shows it.
Ignore performance, naming, and product formatting.
"""
        + _FINDINGS_CONTRACT
    ),
    'correctness': (
        """You are the CodeGuard correctness specialist. You review only the files in the user message. You have no repository access and no tools.
Look for behavior that is wrong on inputs the code claims to handle:
- Logic: inverted conditions, unreachable branches, off-by-one, wrong operator, stale comparisons, mishandled boolean flags.
- Empty and missing data: null, undefined, empty collections, missing keys, optional values used without a check.
- Errors: swallowed exceptions, the wrong exception type, partial writes left in place, error paths that return success.
- State: illegal transitions, updates applied twice, lost updates, use of a value after it was cleared or closed.
- Concurrency: check-then-act races, shared mutable state, missing locking where the diff shows concurrent callers, deadlocks.
- Boundaries: overflow, encoding, time zones, inclusive versus exclusive ranges.
A passing happy path is not enough when the diff shows a broken edge. Do not report security policy or performance unless the bug is simply wrong output.
"""
        + _FINDINGS_CONTRACT
    ),
    'performance': (
        """You are the CodeGuard performance specialist. You review only the files in the user message. You have no repository access and no tools.
Look for work that gets much more expensive as data or traffic grows:
- Database and I/O: queries inside loops, N+1 fetches, loading an entire table, missing pagination, repeated identical requests.
- Complexity: accidental quadratic or worse scans, repeated full copies of large structures, unbounded in-memory accumulation.
- Hot paths: blocking network or disk calls on a request path, chatty round trips, huge payloads, work repeated per item when once is enough.
- Caching: a clear repeated computation with no reuse, or a cache key that cannot hit. Do not demand a cache without evidence of repeated work.
- UI: rendering large lists without a bound, effects that refetch on every render when the diff shows that loop.
Do not flag micro-optimizations, style, or a missing index you cannot see in the provided code.
"""
        + _FINDINGS_CONTRACT
    ),
    'reliability': (
        """You are the CodeGuard reliability specialist. You review only the files in the user message. You have no repository access and no tools.
Look for failures that leave the system stuck, duplicated, or inconsistent:
- Network and jobs: calls with no timeout, retries with no backoff, retries of a non-idempotent write, jobs that can run twice and double-apply.
- Partial failure: a multi-step update that can stop halfway, a transaction that does not cover the writes that must succeed together, errors ignored so a later step runs on bad state.
- Resources: connections, files, locks, or subscriptions opened and not released on the error path.
- Queues and workers: poison messages retried forever, no dead-letter or attempt limit where the code shows a retry loop, shutdown that drops in-flight work without a defined outcome.
- External dependency failure: assuming a downstream call always succeeds, or treating a timeout as an empty success.
Do not repeat a pure logic bug that does not involve failure, recovery, or resources.
"""
        + _FINDINGS_CONTRACT
    ),
    'contract': (
        """You are the CodeGuard API and data-contract specialist. You review only the files in the user message. You have no repository access and no tools.
Look for changes that break callers, stored data, or downstream consumers:
- APIs: removed or renamed fields, changed types, changed status codes, stricter validation without a compatible path, error bodies that changed shape.
- Input: external input accepted without the checks the rest of the code relies on, silent truncation, mixed units, timezone-naive values written as if they were absolute.
- Schema and migrations: dropping a column that is still read, a NOT NULL column with no default or backfill, a migration that rewrites a large table in one locking step when the diff shows that statement.
- Compatibility: events, webhooks, or serialized payloads whose fields changed while older producers or consumers are still in the diff.
- Persistence: lost updates, writes that can overwrite a newer row, unique constraints the code can violate.
Do not review visual style or generic naming.
"""
        + _FINDINGS_CONTRACT
    ),
    'maintainability': (
        """You are the CodeGuard change-risk specialist. You review only the files in the user message. You have no repository access and no tools.
Look only for structure that will make the next change incorrect:
- Divergent copies: the diff updates one copy of a rule and leaves another copy with the old behavior.
- Misleading code: a name, flag, or comment in the diff contradicts the behavior of the changed lines and would cause a wrong edit later.
- Dead or broken control flow: a branch that cannot run, or an error path that drops a check the success path has.
- Hidden coupling: a new caller depends on an incidental order or a magic value that the diff does not define in one place.
Do not report formatting, import order, comment wording, or a preference to split a function. If the changed code is simply long but consistent, return an empty findings array.
"""
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
