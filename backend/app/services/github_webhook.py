import hashlib
import hmac
import json
import logging




logger = logging.getLogger(__name__)

HANDLED_PULL_REQUEST_ACTIONS = frozenset({"opened", "synchronize"})



def verify_github_signature(
    *,
    secret: str,
    body: bytes,
    signature_header: str | None,
) -> bool:
    """Compare ``X-Hub-Signature-256`` with the HMAC-SHA256 of the raw body.

    Args:
        secret: Webhook secret configured on the GitHub App.
        body: Raw request body. Do not re-serialize JSON before hashing.
        signature_header: Header value, expected to start with ``sha256=``.

    Returns:
        True when the signature matches. False when it is missing or wrong.
    """
    if not secret or not signature_header or not signature_header.startswith("sha256="):
        return False

    expected = "sha256=" + hmac.new(
        secret.encode("utf-8"),
        body,
        hashlib.sha256,
    ).hexdigest()

    try:
        return hmac.compare_digest(expected, signature_header)
    except ValueError:
        # compare_digest raises when the strings differ in length
        return False



def parse_github_payload(body: bytes) -> dict:
    """Decode a webhook body after the signature check.

    Args:
        body: Raw request body.

    Returns:
        The JSON object.

    Raises:
        ValueError: The body is not UTF-8 JSON or the JSON value is not an object.
    """
    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Webhook body is not valid JSON") from exc

    if not isinstance(payload, dict):
        raise ValueError("Webhook json must be an object")
    return payload



def summarize_github_event(
    *,
    event_name: str | None,
    delivery_id: str | None,
    payload: dict,
) -> dict:
    """Pull log fields from a webhook payload. Does not sync or create jobs.

    Args:
        event_name: ``X-GitHub-Event`` header.
        delivery_id: ``X-GitHub-Delivery`` header.
        payload: Parsed webhook body.

    Returns:
        Delivery id, event, action, whether this app handles it, GitHub repo
        id, repository full name, and pull request number.
    """
    repository = payload.get("repository") or {}
    pull_request = payload.get("pull_request") or {}
    action = payload.get("action")
    handled = (
        event_name == "pull_request"
        and action in HANDLED_PULL_REQUEST_ACTIONS
    )
    return {
        "delivery_id": delivery_id,
        "event": event_name,
        "action": action,
        "handled": handled,
        "github_repo_id": repository.get("id"),
        "repository": repository.get("full_name"),
        "pr_number": pull_request.get("number"),
    }



def log_github_webhook_event(
    summary: dict,
) -> None:
    """Write one log line for a summarized webhook delivery.

    Args:
        summary: Fields returned by ``summarize_github_event``.

    Returns:
        None.
    """
    if summary["event"] == "ping":
        logger.info("GitHub webhook ping delivery_id=%s", summary["delivery_id"])
        return
    if summary["handled"]:
        logger.info(
            "GitHub webhook handled delivery_id=%s event=%s action=%s repo=%s pr=%s github_repo_id=%s",
            summary["delivery_id"],
            summary["event"],
            summary["action"],
            summary["repository"],
            summary["pr_number"],
            summary["github_repo_id"],
        )
        return
    logger.info(
        "GitHub webhook ignored delivery_id=%s event=%s action=%s",
        summary["delivery_id"],
        summary["event"],
        summary["action"],
    )
