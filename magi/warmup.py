import asyncio
from typing import AsyncIterator

import httpx

from magi.config import OLLAMA_HOST
from magi.core import KEEP_ALIVE

# Cold load of a 7B model from disk can take 30-60s on memory-pressured Macs.
WARMUP_TIMEOUT = 180.0


async def warmup_models(
    models: dict[str, str],
) -> AsyncIterator[tuple[str, str, Exception | None]]:
    """Pre-load each model into Ollama memory in parallel.

    Sends an empty-prompt /api/generate with keep_alive — Ollama treats this as
    a load-without-generate, the fastest way to make a model resident.
    Yields (name, model_id, error_or_None) as each finishes."""
    async with httpx.AsyncClient(timeout=WARMUP_TIMEOUT) as client:
        async def warm_one(name: str, model: str):
            try:
                r = await client.post(
                    f"{OLLAMA_HOST}/api/generate",
                    json={
                        "model": model,
                        "prompt": "",
                        "keep_alive": KEEP_ALIVE,
                        "stream": False,
                    },
                )
                r.raise_for_status()
                return name, model, None
            except Exception as e:
                return name, model, e

        tasks = [asyncio.create_task(warm_one(n, m)) for n, m in models.items()]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()
