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
    "MELCHIOR": "qwen2.5:1.5b",     # Alibaba — small, fast, analytical
    "BALTHASAR": "llama3.2:3b",     # Meta — small, fast, decent reasoning
    "CASPER": "mistral:latest",     # Mistral — bigger but reliable across multi-turn
}


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CONDITIONAL = "CONDITIONAL"


class PersonaResponse(BaseModel):
    verdict: Verdict
    reasoning: str
    asks_in_return: str


class Deliberation:
    """Tracks the per-persona message history across multiple turns.

    Each persona has its own conversation thread because each has its own
    system prompt. When the user responds, all three see their own past
    verdict and reconsider with the new context.
    """

    def __init__(self) -> None:
        self.histories: dict[str, list[dict]] = {name: [] for name in PERSONAS}

    def add_user_message(self, content: str) -> None:
        for name in PERSONAS:
            self.histories[name].append({"role": "user", "content": content})

    def add_response(self, name: str, response: PersonaResponse) -> None:
        # Serialize as JSON so the model sees its prior structured verdict
        # and can stay coherent across turns.
        self.histories[name].append({"role": "assistant", "content": response.model_dump_json()})

    @property
    def turn(self) -> int:
        return sum(1 for m in self.histories["MELCHIOR"] if m["role"] == "user")


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
    """Reasoning models (deepseek-r1, qwen3) emit <think>...</think> blocks
    that can prefix the JSON output. Strip them defensively."""
    return _THINK_BLOCK.sub("", text).strip()


async def _consult(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
) -> PersonaResponse:
    schema = PersonaResponse.model_json_schema()
    response = await client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}] + messages,
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.7},
        },
        timeout=90.0,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return PersonaResponse.model_validate_json(_strip_thinking(content))


async def consult_all_streaming(
    deliberation: Deliberation, models: dict[str, str]
) -> AsyncIterator[tuple[str, PersonaResponse | Exception]]:
    """Yield (name, result) pairs in completion order. Mutates the deliberation
    by appending each successful response to that persona's history."""
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                result = await _consult(client, models[name], PERSONAS[name], deliberation.histories[name])
                deliberation.add_response(name, result)
                return name, result
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


def synthesize(responses: dict[str, PersonaResponse | Exception]) -> str:
    verdicts = [r.verdict for r in responses.values() if isinstance(r, PersonaResponse)]

    if len(verdicts) < 3:
        return f"INCOMPLETE — {3 - len(verdicts)} council member(s) failed to respond"

    accept = verdicts.count(Verdict.ACCEPT)
    reject = verdicts.count(Verdict.REJECT)
    conditional = verdicts.count(Verdict.CONDITIONAL)

    tally = f"{accept}A · {conditional}C · {reject}R"

    if accept == 3:
        return f"UNANIMOUS YES  ({tally})"
    if reject == 3:
        return f"UNANIMOUS NO  ({tally})"
    if conditional == 3:
        return f"UNANIMOUS CONDITIONAL  ({tally})"
    if accept >= 2 and reject == 0:
        return f"MAJORITY YES  ({tally})"
    if reject >= 2 and accept == 0:
        return f"MAJORITY NO  ({tally})"
    if accept >= 1 and reject >= 1:
        return f"COUNCIL SPLIT  ({tally})  →  your call"
    return f"MIXED  ({tally})"
