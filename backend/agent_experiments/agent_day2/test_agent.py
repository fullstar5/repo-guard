import asyncio

from agent_experiments.agent_day2.agent import (
    TEST_PR_ID,
    TEST_USER_ID,
    run_agent,
)

QUESTIONS = (
    "Which files does this PR modify?",
    "Look at the changes about authentication and point out the problems",
)


async def main() -> None:
    """Run the two Day 2 questions against one local pull request.

    Returns:
        None.
    """
    user_id, pull_request_id = TEST_USER_ID, TEST_PR_ID
    for question in QUESTIONS:
        await run_agent(
            question,
            user_id=user_id,
            pull_request_id=pull_request_id,
        )


if __name__ == "__main__":
    asyncio.run(main())
