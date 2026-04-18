from __future__ import annotations

import asyncio

from src.config import settings

api_semaphore = asyncio.Semaphore(settings.max_concurrent_api)
ai_semaphore = asyncio.Semaphore(settings.max_concurrent_ai)
