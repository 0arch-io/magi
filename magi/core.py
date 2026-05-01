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


class Rebuttal(BaseModel):
    """What a council member says to the other two after seeing their votes."""
    response: str           # 1-3 sentences directly addressing the other members
    final_verdict: Verdict  # may match initial or be updated based on debate


class Deliberation:
    """Tracks the per-persona message history across multiple turns.

    Each persona has its own conversation thread because each has its own
    system prompt. When the user responds, all three see their own past
    final verdict and reconsider with the new context.
    """

    def __init__(self) -> None:
        self.histories: dict[str, list[dict]] = {name: [] for name in PERSONAS}

    def add_user_message(self, content: str) -> None:
        for name in PERSONAS:
            self.histories[name].append({"role": "user", "content": content})

    def commit_response(self, name: str, response: PersonaResponse) -> None:
        """Append the FINAL persona response (post-debate) to history."""
        self.histories[name].append({"role": "assistant", "content": response.model_dump_json()})

    @property
    def turn(self) -> int:
        return sum(1 for m in self.histories["MELCHIOR"] if m["role"] == "user")


_THINK_BLOCK = re.compile(r"<think>.*?</think>", re.DOTALL)


def _strip_thinking(text: str) -> str:
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


async def _rebut(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
    own_vote: PersonaResponse,
    others: dict[str, PersonaResponse],
) -> Rebuttal:
    """Show this persona the other two members' votes; ask for a rebuttal + final verdict."""
    others_text = "\n\n".join(
        f"{name}: {r.verdict.value} — {r.reasoning}"
        for name, r in others.items()
    )
    debate_prompt = (
        "The other two council members have just voted. Here is what they said:\n\n"
        f"{others_text}\n\n"
        "Now respond to them. Address them by name. Push back on what you disagree with, "
        "agree with what's right, point out what they missed. Stay in your lens, keep it 1-3 sentences. "
        "Then give your final verdict — keep it the same OR change it if their argument genuinely "
        "moved you. Do not change just to be agreeable."
    )

    schema = Rebuttal.model_json_schema()
    debate_messages = (
        messages
        + [{"role": "assistant", "content": own_vote.model_dump_json()}]
        + [{"role": "user", "content": debate_prompt}]
    )

    response = await client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}] + debate_messages,
            "format": schema,
            "stream": False,
            "options": {"temperature": 0.7},
        },
        timeout=90.0,
    )
    response.raise_for_status()
    content = response.json()["message"]["content"]
    return Rebuttal.model_validate_json(_strip_thinking(content))


async def _vote_round(
    deliberation: Deliberation, models: dict[str, str]
) -> AsyncIterator[tuple[str, PersonaResponse | Exception]]:
    """Round 1: each persona votes independently, in parallel. Does NOT mutate history."""
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                return name, await _consult(client, models[name], PERSONAS[name], deliberation.histories[name])
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


async def _debate_round(
    deliberation: Deliberation,
    models: dict[str, str],
    initial_votes: dict[str, PersonaResponse],
) -> AsyncIterator[tuple[str, Rebuttal | Exception]]:
    """Round 2: each persona sees the others' votes and rebuts. Parallel."""
    async with httpx.AsyncClient() as client:
        async def rebut(name: str):
            own = initial_votes[name]
            others = {n: v for n, v in initial_votes.items() if n != name}
            try:
                return name, await _rebut(client, models[name], PERSONAS[name], deliberation.histories[name], own, others)
            except Exception as e:
                return name, e

        tasks = [asyncio.create_task(rebut(n)) for n in initial_votes.keys()]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()


async def deliberate(
    deliberation: Deliberation, models: dict[str, str]
) -> AsyncIterator[tuple[str, str, object]]:
    """Full two-round council deliberation.

    Yields events as they happen:
      ("vote", name, PersonaResponse | Exception)
      ("rebuttal", name, Rebuttal | Exception)

    On completion, the deliberation's history reflects each persona's FINAL
    post-debate verdict (or initial vote if the debate round failed for them).
    """
    initial_votes: dict[str, PersonaResponse] = {}
    failed: dict[str, Exception] = {}

    async for name, result in _vote_round(deliberation, models):
        if isinstance(result, PersonaResponse):
            initial_votes[name] = result
        else:
            failed[name] = result
        yield ("vote", name, result)

    # Need at least two valid voters for a real debate.
    if len(initial_votes) < 2:
        for name, response in initial_votes.items():
            deliberation.commit_response(name, response)
        return

    final_responses: dict[str, PersonaResponse] = {}
    async for name, rebuttal in _debate_round(deliberation, models, initial_votes):
        yield ("rebuttal", name, rebuttal)
        if isinstance(rebuttal, Rebuttal):
            initial = initial_votes[name]
            final_responses[name] = PersonaResponse(
                verdict=rebuttal.final_verdict,
                reasoning=initial.reasoning,
                asks_in_return=initial.asks_in_return,
            )
        else:
            # rebuttal failed — keep the initial vote as final
            final_responses[name] = initial_votes[name]

    for name, response in final_responses.items():
        deliberation.commit_response(name, response)


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
