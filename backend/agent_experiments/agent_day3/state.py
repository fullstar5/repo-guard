import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

CHECKPOINT_PATH = Path(__file__).resolve().parent / "checkpoint.json"

@dataclass
class AgentState:
    user_id: int
    pull_request_id: int
    round_index: int = 0
    read_files: dict[str, dict[str, object]] = field(default_factory=dict)
    tool_summaries: list[dict[str, object]] = field(default_factory=list)
    messages: list[dict[str, object]] = field(default_factory=list)

    def save(self) -> None:
        """Write this state to the experiment checkpoint file.
        Returns:
            None.
        """
        CHECKPOINT_PATH.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    @classmethod
    def load(cls) -> "AgentState":
        """Load the checkpoint written by the last run.
        Returns:
            The saved state.
        Raises:
            RuntimeError: The checkpoint file is missing.
            TypeError: The checkpoint JSON is not an object.
        """
        if not CHECKPOINT_PATH.is_file():
            raise RuntimeError(f"No checkpoint at {CHECKPOINT_PATH}")
        payload = json.loads(CHECKPOINT_PATH.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise TypeError("Checkpoint must be a JSON object.")
        return cls(
            user_id=int(payload["user_id"]),
            pull_request_id=int(payload["pull_request_id"]),
            round_index=int(payload.get("round_index", 0)),
            read_files=dict(payload.get("read_files") or {}),
            tool_summaries=list(payload.get("tool_summaries") or []),
            messages=list(payload.get("messages") or []),
        )
        