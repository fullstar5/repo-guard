import asyncio

from agent_experiments.agent_day3.agent import run_agent


async def main() -> None:
    """Start a review and leave a checkpoint for the follow-up command.

    Returns:
        None.
    """
    await run_agent(
        "Read the authentication-related changes and point out the problems.",
        resume=False,
    )


if __name__ == "__main__":
    asyncio.run(main())