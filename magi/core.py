import asyncio
import os
import re
from enum import Enum
from typing import AsyncIterator

import httpx
from pydantic import BaseModel

from magi.personas import PERSONAS


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


# Three different model families = three genuinely independent perspectives.
# Faithful to MAGI canon (three independent computers, not three personas of one).
DEFAULT_MODELS = {
    "MELCHIOR": "qwen2.5:7b",       # Alibaba — analytical, structured
    "BALTHASAR": "llama3.1:8b",     # Meta — balanced, broad-knowledge
    "CASPER": "mistral:latest",     # Mistral — different cultural lens
}


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CONDITIONAL = "CONDITIONAL"


class PersonaResponse(BaseModel):
    verdict: Verdict
    reasoning: str
    key_concern: str


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Reasoning models (deepseek-r1, qwen3) emit <think>...</think> blocks
    that can prefix the JSON output. Strip them defensively."""
    return _THINK_BLOCK.sub("", text).strip()


async def _consult(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    question: str,
) -> PersonaResponse:
    schema = PersonaResponse.model_json_schema()
    response = await client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": question},
            ],
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.7},
        },
        timeout=300.0,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return PersonaResponse.model_validate_json(_strip_thinking(content))


async def consult_all_streaming(
    question: str, models: dict[str, str]
) -> AsyncIterator[tuple[str, PersonaResponse | Exception]]:
    """Yield (name, result) pairs in completion order."""
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                return name, await _consult(client, models[name], PERSONAS[name], question)
            except Exception as e:
                return name, e

        tasks = [asyncio.create_task(wrap(n)) for n in PERSONAS.keys()]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()


async def consult_all(question: str, models: dict[str, str]) -> dict:
    results: dict[str, PersonaResponse | Exception] = {}
    async for name, result in consult_all_streaming(question, models):
        results[name] = result
    return results


def synthesize(responses: dict[str, PersonaResponse | Exception]) -> str:
    verdicts = [r.verdict for r in responses.values() if isinstance(r, PersonaResponse)]

    if len(verdicts) < 3:
        return f"INCOMPLETE — {3 - len(verdicts)} persona(s) failed to respond"

    accept = verdicts.count(Verdict.ACCEPT)
    reject = verdicts.count(Verdict.REJECT)
    conditional = verdicts.count(Verdict.CONDITIONAL)

    tally = f"{accept}A · {conditional}C · {reject}R"

    if accept == 3:
        return f"UNANIMOUS ACCEPT  ({tally})"
    if reject == 3:
        return f"UNANIMOUS REJECT  ({tally})"
    if conditional == 3:
        return f"UNANIMOUS CONDITIONAL  ({tally})"
    if accept >= 2 and reject == 0:
        return f"MAJORITY ACCEPT  ({tally})"
    if reject >= 2 and accept == 0:
        return f"MAJORITY REJECT  ({tally})"
    if accept >= 1 and reject >= 1:
        return f"DEADLOCK  ({tally})  →  human decides"
    return f"MIXED  ({tally})"
