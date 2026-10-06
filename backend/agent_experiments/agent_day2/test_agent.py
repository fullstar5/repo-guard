import asyncio

from agent_experiments.agent_day2.agent import bound_ids_from_env, run_agent

QUESTIONS = (
    "这个 PR 改了哪些文件？",
    "看认证相关改动，指出问题。",
)


async def main() -> None:
    """Run the two Day 2 questions against one local pull request.

    Returns:
        None.
    """
    user_id, pull_request_id = bound_ids_from_env()
    for question in QUESTIONS:
        await run_agent(
            question,
            user_id=user_id,
            pull_request_id=pull_request_id,
        )


if __name__ == "__main__":
    asyncio.run(main())
