"""Direct pipeline runner — bypasses FastAPI for testing.

Usage:
    uv run python run_pipeline.py              # Run content production (from intents)
    uv run python run_pipeline.py --mine       # Run intent mining
    uv run python run_pipeline.py --grow       # Run growth loop (expand covered clusters)
    uv run python run_pipeline.py --all        # Mine intents, then produce content
"""
import asyncio
import sys

from src.storage.database import init_db, close_db
from src.scheduler.jobs import intent_mining_pipeline, main_pipeline, growth_loop
from src.utils.logging import setup_logging


async def run():
    setup_logging("INFO")
    await init_db()
    print("DB connected.")

    args = set(sys.argv[1:])

    if "--all" in args:
        print("Running intent mining → content production...")
        await intent_mining_pipeline()
        await main_pipeline()
    elif "--mine" in args:
        print("Running intent mining...")
        await intent_mining_pipeline()
    elif "--grow" in args:
        print("Running growth loop...")
        await growth_loop()
    else:
        print("Running content production from pending intents...")
        await main_pipeline()

    print("Done.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(run())
