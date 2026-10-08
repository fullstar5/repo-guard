import asyncio
from agent_experiments.agent_day1.agent import run_agent



QUESTIONS = (
    "Review PR #42 in mark/codeguard.",
    "Who authored PR #7?",
    "What is 2 + 2?",
)
async def main() -> None:
    """Run the three Day 1 questions in order.
    Returns:
        None.
    """
    for question in QUESTIONS:
        await run_agent(question)
if __name__ == "__main__":
    asyncio.run(main())