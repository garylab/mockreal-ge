"""Direct pipeline runner — bypasses FastAPI for testing."""
import asyncio
from src.storage.database import get_pool, close_pool
from src.scheduler.jobs import main_pipeline
from src.utils.logging import setup_logging

async def run():
    setup_logging("INFO")
    await get_pool()
    print("DB connected. Running pipeline...")
    await main_pipeline()
    print("Pipeline done.")
    await close_pool()

if __name__ == "__main__":
    asyncio.run(run())
