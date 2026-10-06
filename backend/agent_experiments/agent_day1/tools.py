import json
from collections.abc import Callable


def get_pull_request_info(repo: str, pr_number: int) -> dict[str, object]:
    """Return canned pull request metadata.
    Args:
        repo: Repository the model asked about, such as ``mark/codeguard``.
        pr_number: Pull request number the model asked about.
    Returns:
        The requested repo and number, plus fixed title, author, and diff size.
    """
    return {
        "repo": repo,
        "pr_number": pr_number,
        "title": "Fix authentication bug",
        "author": "mark",
        "files_changed": 4,
        "additions": 120,
        "deletions": 35,
    }



TOOLS: list[dict[str, object]] = [
    {
        "type": "function",
        "function": {
            "name": "get_pull_request_info",
            "description": "Get metadata about a Github PR",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "repo": {"type": "string"},
                    "pr_number": {"type": "integer"},
                },
                "required": ["repo", "pr_number"],
                "additionalProperties": False,
            },
        },
    },
]


_TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, object]]] = {
    "get_pull_request_info": get_pull_request_info,
}



def execute_tool(name:str, arguments: dict[str, object]) -> dict[str, object]:
    """Run one tool the model selected.
    Args:
        name: Tool name from the assistant message.
        arguments: Parsed function arguments.
    Returns:
        The tool payload, or an error object the model can read.
    """
    function = _TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"error": f"Unknown tool: {name}"}

    repo = arguments.get("repo")
    pr_number = arguments.get("pr_number")
    if not isinstance(repo, str) or isinstance(pr_number, bool) or not isinstance(pr_number, int):
        return {"error": "repo must be a string and pr_number must be an integer."}

    return function(repo=repo, pr_number=pr_number)



def parse_tool_arguments(raw_arguments: object) -> dict[str, object]:
    """Parse a tool call's arguments field.
    Args:
        raw_arguments: JSON string from Chat Completions, or a dict a provider already parsed.
    Returns:
        An arguments object.
    Raises:
        json.JSONDecodeError: The string is not JSON.
        TypeError: The value is not an object.
    """
    if isinstance(raw_arguments, str):
        parsed = json.loads(raw_arguments)
    else:
        parsed = raw_arguments
    if not isinstance(parsed, dict):
        raise TypeError("Tool arguments must be a JSON object.")
    return parsed



