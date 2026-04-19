"""Direct pipeline runner — bypasses FastAPI for testing."""
import asyncio
from src.storage.database import init_db, close_db
from src.scheduler.jobs import main_pipeline
from src.utils.logging import setup_logging

async def run():
    setup_logging("INFO")
    await init_db()
    print("DB connected. Running pipeline...")
    await main_pipeline()
    print("Pipeline done.")
    await close_db()

if __name__ == "__main__":
    asyncio.run(run())
