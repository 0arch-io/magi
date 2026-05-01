import asyncio
import os
import re
from enum import Enum
from typing import AsyncIterator

import httpx
from pydantic import BaseModel

from magi.personas import PERSONAS


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_DELIBERATION_ROUNDS = 4  # 1 vote + up to 3 debate rounds


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
    """What a council member says to the others after seeing their current positions."""
    response: str
    final_verdict: Verdict


class Deliberation:
    def __init__(self) -> None:
        self.histories: dict[str, list[dict]] = {name: [] for name in PERSONAS}

    def add_user_message(self, content: str) -> None:
        for name in PERSONAS:
            self.histories[name].append({"role": "user", "content": content})

    def commit_response(self, name: str, response: PersonaResponse) -> None:
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
    own_position: PersonaResponse,
    others: dict[str, PersonaResponse],
    round_num: int,
) -> Rebuttal:
    """Show the persona the others' current positions and ask for a response + verdict."""
    others_text = "\n\n".join(
        f"{name}: {r.verdict.value} — {r.reasoning}"
        for name, r in others.items()
    )

    if round_num == 2:
        opener = "The other council members have just voted. Here is what they said:"
        closer = (
            "Now respond to them. Address them by name. Push back on what you disagree "
            "with, agree with what is right, point out what they missed. Stay in your "
            "lens, keep it 1-3 sentences. Then give your final verdict for this round — "
            "keep it the same OR change it if their argument moved you."
        )
    else:
        opener = (
            f"This is round {round_num} of the deliberation. The other members' "
            "latest positions:"
        )
        closer = (
            "Respond to the latest points raised. Push toward agreement where you "
            "can, hold the line on real disagreements. The deliberation ends at "
            f"round {MAX_DELIBERATION_ROUNDS} — sharpen your position. 1-3 sentences. "
            "Final verdict: same as last round OR updated based on what was said."
        )

    debate_prompt = f"{opener}\n\n{others_text}\n\n{closer}"

    schema = Rebuttal.model_json_schema()
    debate_messages = (
        messages
        + [{"role": "assistant", "content": own_position.model_dump_json()}]
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
    current_positions: dict[str, PersonaResponse],
    round_num: int,
) -> AsyncIterator[tuple[str, Rebuttal | Exception]]:
    async with httpx.AsyncClient() as client:
        async def rebut(name: str):
            own = current_positions[name]
            others = {n: v for n, v in current_positions.items() if n != name}
            try:
                return name, await _rebut(client, models[name], PERSONAS[name], deliberation.histories[name], own, others, round_num)
            except Exception as e:
                return name, e

        tasks = [asyncio.create_task(rebut(n)) for n in current_positions.keys()]
        try:
            for coro in asyncio.as_completed(tasks):
                yield await coro
        finally:
            for t in tasks:
                if not t.done():
                    t.cancel()


def _is_consensus(positions: dict[str, PersonaResponse]) -> bool:
    verdicts = [p.verdict for p in positions.values()]
    return len(verdicts) >= 2 and len(set(verdicts)) == 1


async def iterative_deliberate(
    deliberation: Deliberation, models: dict[str, str], max_rounds: int = MAX_DELIBERATION_ROUNDS
) -> AsyncIterator[tuple]:
    """Iterative deliberation: vote round + debate rounds until consensus or max rounds.

    Yields events for the UI to render:
      ("round_start", round_num)
      ("vote", name, PersonaResponse | Exception)             # round 1
      ("rebuttal", name, Rebuttal | Exception)                # rounds 2+
      ("done", outcome, current_positions)  # outcome ∈ {"consensus","deadlock","incomplete"}

    Mutates deliberation: commits the final post-deliberation responses to history.
    """
    yield ("round_start", 1)
    initial_votes: dict[str, PersonaResponse | Exception] = {}
    async for name, result in _vote_round(deliberation, models):
        initial_votes[name] = result
        yield ("vote", name, result)

    valid: dict[str, PersonaResponse] = {n: v for n, v in initial_votes.items() if isinstance(v, PersonaResponse)}

    if len(valid) < 2:
        for name, response in valid.items():
            deliberation.commit_response(name, response)
        yield ("done", "incomplete", valid)
        return

    current_positions = dict(valid)

    if _is_consensus(current_positions):
        for name, response in current_positions.items():
            deliberation.commit_response(name, response)
        yield ("done", "consensus", current_positions)
        return

    for round_num in range(2, max_rounds + 1):
        yield ("round_start", round_num)
        async for name, rebuttal in _debate_round(deliberation, models, current_positions, round_num):
            yield ("rebuttal", name, rebuttal)
            if isinstance(rebuttal, Rebuttal):
                prev = current_positions[name]
                current_positions[name] = PersonaResponse(
                    verdict=rebuttal.final_verdict,
                    reasoning=prev.reasoning,
                    asks_in_return=prev.asks_in_return,
                )

        if _is_consensus(current_positions):
            for name, response in current_positions.items():
                deliberation.commit_response(name, response)
            yield ("done", "consensus", current_positions)
            return

    # Hit max rounds without consensus
    for name, response in current_positions.items():
        deliberation.commit_response(name, response)
    yield ("done", "deadlock", current_positions)


def synthesize(
    responses: dict[str, PersonaResponse | Exception],
    outcome: str = "auto",
) -> str:
    """outcome ∈ {"consensus", "deadlock", "incomplete", "auto"}.
    'auto' detects from the verdicts: same → consensus, otherwise deadlock."""
    valid = [r for r in responses.values() if isinstance(r, PersonaResponse)]
    n = len(valid)

    if n < 2:
        return f"INCOMPLETE — only {n} council member(s) responded"

    accept = sum(1 for r in valid if r.verdict == Verdict.ACCEPT)
    reject = sum(1 for r in valid if r.verdict == Verdict.REJECT)
    conditional = sum(1 for r in valid if r.verdict == Verdict.CONDITIONAL)
    tally = f"{accept}A · {conditional}C · {reject}R"

    if outcome == "auto":
        outcome = "consensus" if len({r.verdict for r in valid}) == 1 else "deadlock"

    if outcome == "consensus":
        if accept == n:
            return f"CONSENSUS — YES  ({tally})"
        if reject == n:
            return f"CONSENSUS — NO  ({tally})"
        return f"CONSENSUS — CONDITIONAL  ({tally})"

    # deadlock
    if accept > n / 2 and reject == 0:
        return f"DEADLOCK — leans YES  ({tally})  →  your call"
    if reject > n / 2 and accept == 0:
        return f"DEADLOCK — leans NO  ({tally})  →  your call"
    return f"DEADLOCK — split  ({tally})  →  your call"
