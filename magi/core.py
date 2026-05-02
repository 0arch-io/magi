import asyncio
import os
import re
from enum import Enum
from typing import AsyncIterator

import httpx
from pydantic import BaseModel, Field, model_validator

from magi.personas import PERSONAS, get_system_prompt


OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_DELIBERATION_ROUNDS = 3  # 1 vote + up to 2 debate rounds (was 4 — late rounds added little)


DEFAULT_MODELS = {
    "MELCHIOR": "qwen2.5:7b",       # Alibaba — 7B for reliable multi-round debate + identity rule
    "BALTHASAR": "qwen3:4b",        # Qwen3 4B — promoted from llama3.2:3b in v0.10.4 (3B llama wouldn't stop interrogating the user despite explicit prompt rules; qwen3:4b follows instructions cleanly at similar footprint ~2.5GB)
    "CASPER": "mistral:latest",     # Mistral 7B — different family, reliable across multi-turn
}


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CONDITIONAL = "CONDITIONAL"


_BANNED_CONDITION_PHRASES = (
    "clear plan", "clear vision", "manageable scope", "sufficient resources",
    "realistic timeline", "long-term goals", "personal values",
    "regularly reassess", "explore additional resources",
    "concise mission statement", "balance ambition", "specific aspects",
    "core values",
)


def _condition_is_vague(condition: str) -> bool:
    if not condition.strip():
        return True
    low = condition.lower()
    return any(phrase in low for phrase in _BANNED_CONDITION_PHRASES)


class PersonaResponse(BaseModel):
    verdict: Verdict
    reasoning: str = Field(
        ...,
        min_length=20,
        description="1-3 sharp DECLARATIVE sentences about the user's situation. State your read. Never end a sentence with '?'. Never ask the user clarifying questions. Minimum one complete sentence.",
    )
    condition: str = Field(
        default="",
        description="REQUIRED when verdict=CONDITIONAL: ONE concrete blocker tied to specifics in THIS user's question (their actual numbers, people, constraints, situation). NOT a generic life-advice template. Banned vague phrases: 'clear plan', 'clear vision', 'manageable scope', 'sufficient resources', 'realistic timeline', 'long-term goals', 'mission statement', 'balance ambition', 'core values'. If you cannot name a blocker tied to real specifics, vote ACCEPT or REJECT instead. Empty string when verdict is ACCEPT or REJECT.",
    )

    @model_validator(mode="after")
    def _coerce_hedged_conditional(self):
        if self.verdict == Verdict.CONDITIONAL and _condition_is_vague(self.condition):
            self.verdict = Verdict.ACCEPT
            self.condition = ""
        return self


class Rebuttal(BaseModel):
    """What a council member says to the others after seeing their current positions."""
    response: str = Field(
        ...,
        min_length=20,
        description="1-3 DECLARATIVE sentences responding to the others by name. Push back, hold your line. Never address the user with questions. Never end a sentence with '?'. Minimum one complete sentence.",
    )
    final_verdict: Verdict
    condition: str = Field(
        default="",
        description="REQUIRED when final_verdict=CONDITIONAL: same rules as initial vote. A concrete blocker tied to specifics in THIS question, not a generic template. Banned vague phrases: same list as initial vote. Empty string for ACCEPT or REJECT.",
    )

    @model_validator(mode="after")
    def _coerce_hedged_conditional(self):
        if self.final_verdict == Verdict.CONDITIONAL and _condition_is_vague(self.condition):
            self.final_verdict = Verdict.ACCEPT
            self.condition = ""
        return self


class Deliberation:
    """Tracks per-member message history across multiple turns. Members are
    typically the 3 core MAGI plus any specialists invited via /invite."""

    def __init__(self, member_names: list[str]) -> None:
        self.histories: dict[str, list[dict]] = {name: [] for name in member_names}

    def add_user_message(self, content: str) -> None:
        for name in self.histories:
            self.histories[name].append({"role": "user", "content": content})

    def commit_response(self, name: str, response: PersonaResponse) -> None:
        self.histories[name].append({"role": "assistant", "content": response.model_dump_json()})

    def add_member(self, name: str) -> None:
        """Add a new member mid-deliberation. They get backfilled with the prior
        USER messages so they have the same context, but no fabricated assistant
        responses (since they did not say anything yet)."""
        if name in self.histories:
            return
        if self.histories:
            sample = next(iter(self.histories.values()))
            self.histories[name] = [m for m in sample if m["role"] == "user"]
        else:
            self.histories[name] = []

    def remove_member(self, name: str) -> None:
        self.histories.pop(name, None)

    @property
    def turn(self) -> int:
        if "MELCHIOR" in self.histories:
            return sum(1 for m in self.histories["MELCHIOR"] if m["role"] == "user")
        if self.histories:
            return sum(1 for m in next(iter(self.histories.values())) if m["role"] == "user")
        return 0


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

    identity_anchor = (
        "REMEMBER: you are speaking ABOUT the user's situation. "
        "Use 'they' / 'the user' / 'their'. Never 'I' / 'my' / 'we'. "
        "The facts in this question belong to the user, not you."
    )

    if round_num == 2:
        opener = "The other council members have just voted. Here is what they said:"
        closer = (
            "Address them by name. Push back on what you disagree with. Point out "
            "what they missed. Stay in your lens. 1-3 sentences.\n\n"
            "Then give your final verdict for this round. HOLD YOUR LINE unless a "
            "real argument was made that exposed new information or a flaw in your "
            "reasoning. Convergence for its own sake is failure — if you still "
            "believe your verdict, keep it. Drifting to CONDITIONAL because others "
            "did is hedging, not deliberating. If you do vote CONDITIONAL, you must "
            "name ONE concrete blocker — no vague hedges."
        )
    else:
        opener = (
            f"This is round {round_num} of the deliberation. The other members' "
            "latest positions:"
        )
        closer = (
            "Respond to the latest points. HOLD YOUR LINE unless a real argument "
            "exposed new information or a flaw. Convergence for its own sake is "
            "failure. Stay in your lens. 1-3 sentences.\n\n"
            "Final verdict: same as last round OR updated only if you were "
            "genuinely persuaded by a specific argument. If CONDITIONAL, name ONE "
            "concrete blocker."
        )

    debate_prompt = f"{identity_anchor}\n\n{opener}\n\n{others_text}\n\n{closer}"

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
                return name, await _consult(client, models[name], get_system_prompt(name), deliberation.histories[name])
            except Exception as e:
                return name, e

        tasks = [asyncio.create_task(wrap(n)) for n in models.keys()]
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
                return name, await _rebut(client, models[name], get_system_prompt(name), deliberation.histories[name], own, others, round_num)
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
                new_condition = rebuttal.condition if rebuttal.final_verdict == Verdict.CONDITIONAL else ""
                current_positions[name] = PersonaResponse(
                    verdict=rebuttal.final_verdict,
                    reasoning=prev.reasoning,
                    condition=new_condition,
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
