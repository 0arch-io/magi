import asyncio
import re
from enum import Enum
from typing import AsyncIterator

import httpx
from pydantic import BaseModel, Field, model_validator

from magi.config import OLLAMA_HOST
from magi.personas import (
    get_choice_prompt,
    get_decision_prompt,
    get_recommend_prompt,
)

MAX_DELIBERATION_ROUNDS = 3
KEEP_ALIVE = "30m"
MAX_RESPONSE_BYTES = 1_048_576
MAX_INPUT_CHARS = 10_000


class OllamaUnavailable(Exception):
    """Raised when Ollama can't be reached."""
    def __init__(self, host: str = OLLAMA_HOST):
        super().__init__(
            f"cannot connect to Ollama at {host}\n\n"
            "  install:  https://ollama.com\n"
            "  start:    ollama serve\n"
            "  custom:   OLLAMA_HOST=http://host:port magi"
        )


def _wrap_connect_error(exc: Exception) -> Exception:
    if isinstance(exc, httpx.ConnectError):
        return OllamaUnavailable()
    return exc


DEFAULT_MODELS = {
    "MELCHIOR": "qwen3:14b",
    "BALTHASAR": "phi4:latest",
    "CASPER": "hermes3:8b",
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
    "core values", "well-defined goals", "proper preparation",
    "adequate funding", "solid foundation", "strong commitment",
    "careful consideration", "thorough research", "good understanding",
    "appropriate measures", "reasonable expectations",
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


class ChoiceResponse(BaseModel):
    chosen_option: str = Field(
        ...,
        min_length=1,
        description="The option you pick. Must EXACTLY match one of the options provided in the question (case-insensitive). Pick exactly one — no 'depends', no combining, no 'both'.",
    )
    reasoning: str = Field(
        ...,
        min_length=20,
        description="1-3 sharp DECLARATIVE sentences for why you picked this option over the others. State your read from your lens. Never address the user with questions. Never end a sentence with '?'.",
    )


class ChoiceRebuttal(BaseModel):
    response: str = Field(
        ...,
        min_length=20,
        description="1-3 DECLARATIVE sentences responding to the others by name. Push back if their pick is wrong, hold your line. Never address the user with questions.",
    )
    final_choice: str = Field(
        ...,
        min_length=1,
        description="Your final pick this round. Same option as before OR changed only if a real argument moved you.",
    )


_BANNED_RECOMMENDATION_PHRASES = (
    "something you're passionate about", "something you are passionate about",
    "what aligns with your values", "aligns with your values",
    "a project that excites you", "what excites you most",
    "follow your heart", "follow your passion",
    "what feels right", "what resonates with you",
    "find your purpose", "discover your purpose",
    "anything that interests you", "whatever you want",
    "trust your gut",
    "consider building", "consider creating", "consider developing",
    "consider starting", "consider exploring", "consider pursuing",
    "consider trying", "consider playing", "consider reading",
    "consider watching", "consider learning", "consider taking",
    "look into", "explore options", "explore opportunities",
    "explore a ", "try a ", "play a ",
    "a project that addresses", "a project that solves",
    "a game with ", "a book with ", "a tool with ",
    "something that combines", "something that leverages",
    "something with a ", "an initiative that", "a venture that",
)


def _recommendation_is_vague(rec: str) -> bool:
    if len(rec.strip()) < 10:
        return True
    low = rec.lower()
    return any(phrase in low for phrase in _BANNED_RECOMMENDATION_PHRASES)


class RecommendResponse(BaseModel):
    recommendation: str = Field(
        ...,
        min_length=10,
        description=(
            "ONE concrete, specific recommendation. NAME IT. "
            "If the user asks for a game, name the game (e.g. 'Hades'). If they ask for a project, name the project. "
            "A category ('a game with X') is NOT a recommendation. A specific name IS. "
            "Do NOT start with 'Consider', 'Explore', 'Try', or 'A game with'. Just name the thing directly."
        ),
    )
    reasoning: str = Field(
        ...,
        min_length=20,
        description="1-3 sharp DECLARATIVE sentences for why YOUR LENS picks this. Never end a sentence with '?'. Never interview the user.",
    )

    @model_validator(mode="after")
    def _reject_vague(self):
        if _recommendation_is_vague(self.recommendation):
            raise ValueError(f"recommendation is too vague: {self.recommendation!r}")
        return self


class RecommendRebuttal(BaseModel):
    response: str = Field(
        ...,
        min_length=20,
        description="1-3 DECLARATIVE sentences responding to the others by name. Hold your line unless a real argument moved you.",
    )
    final_recommendation: str = Field(
        ...,
        min_length=10,
        description="Your final concrete recommendation this round. Same as before OR refined/changed only if persuaded. Same vagueness rules.",
    )

    @model_validator(mode="after")
    def _reject_vague(self):
        if _recommendation_is_vague(self.final_recommendation):
            raise ValueError(f"final_recommendation is too vague: {self.final_recommendation!r}")
        return self


class Deliberation:
    """Per-member message history across deliberation turns."""

    def __init__(self, member_names: list[str]) -> None:
        self.histories: dict[str, list[dict]] = {name: [] for name in member_names}

    def add_user_message(self, content: str) -> None:
        if len(content) > MAX_INPUT_CHARS:
            content = content[:MAX_INPUT_CHARS]
        for name in self.histories:
            self.histories[name].append({"role": "user", "content": content})

    def commit_response(self, name: str, response: PersonaResponse) -> None:
        self.histories[name].append({"role": "assistant", "content": response.model_dump_json()})

    def add_member(self, name: str) -> None:
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
_NAME_PREFIX = re.compile(
    r"^(MELCHIOR|BALTHASAR|CASPER|BANKER|THERAPIST|LAWYER|COACH|DOCTOR)(?:'s|s')?"
    r"(?:\s+(?:final\s+|my\s+)?(?:recommendation|recommends|pick|picks|verdict|votes|vote|choice|chooses|chose|says|said|decides|decided|answers|answer))?"
    r"\s*[:\-—]\s*",
    re.IGNORECASE,
)
_VERDICT_PREFIX = re.compile(r"^(ACCEPT|REJECT|CONDITIONAL)\s*[-—:]\s*", re.IGNORECASE)


def _strip_thinking(text: str) -> str:
    return _THINK_BLOCK.sub("", text).strip()


def _strip_persona_prefixes(text: str) -> str:
    s = _sanitize_llm_output(text.strip())
    for _ in range(3):
        before = s
        s = _NAME_PREFIX.sub("", s).strip()
        s = _VERDICT_PREFIX.sub("", s).strip()
        if s == before:
            break
    return s


_REC_FILLER_PREFIX = re.compile(
    r"^(?:try|play|explore|check out|look into|consider(?: trying)?)\s+",
    re.IGNORECASE,
)


def _clean_recommendation(rec: str) -> str:
    rec = _sanitize_llm_output(rec.strip())
    rec = _strip_persona_prefixes(rec)
    rec = _REC_FILLER_PREFIX.sub("", rec).strip()
    if ": " in rec:
        before_colon = rec.split(": ", 1)[0]
        if len(before_colon) >= 3 and len(before_colon) <= 80:
            rec = before_colon
    return rec


# think=False prevents qwen3 from leaking chain-of-thought into the response
def _ollama_options(temperature: float = 0.7, num_predict: int = 1200) -> dict:
    return {
        "temperature": temperature,
        "num_predict": num_predict,
        "think": False,
    }


def _check_response_size(response: httpx.Response) -> None:
    content_length = response.headers.get("content-length")
    if content_length and int(content_length) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Ollama response too large ({content_length} bytes, cap {MAX_RESPONSE_BYTES})")
    if len(response.content) > MAX_RESPONSE_BYTES:
        raise ValueError(f"Ollama response too large ({len(response.content)} bytes, cap {MAX_RESPONSE_BYTES})")


def _check_content_type(response: httpx.Response) -> None:
    ct = response.headers.get("content-type", "")
    if ct and "json" not in ct and "text" not in ct:
        raise ValueError(f"unexpected content-type from Ollama: {ct[:60]}")


_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[^[(\n]")
_CONTROL_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def _sanitize_llm_output(text: str) -> str:
    text = _ANSI_ESCAPE.sub("", text)
    text = _CONTROL_CHARS.sub("", text)
    return text


def _validate_response(response: httpx.Response) -> None:
    _check_response_size(response)
    _check_content_type(response)


async def _consult(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
) -> PersonaResponse:
    schema = PersonaResponse.model_json_schema()
    try:
        response = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "system", "content": system}] + messages,
                "format": schema,
                "stream": False,
                "keep_alive": KEEP_ALIVE,
                "options": _ollama_options(temperature=0.7),
            },
            timeout=90.0,
        )
    except httpx.ConnectError:
        raise OllamaUnavailable()
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
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
            "keep_alive": KEEP_ALIVE,
            "options": _ollama_options(temperature=0.7),
        },
        timeout=90.0,
    )
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
    return Rebuttal.model_validate_json(_strip_thinking(content))


async def _vote_round(
    deliberation: Deliberation, models: dict[str, str]
) -> AsyncIterator[tuple[str, PersonaResponse | Exception]]:
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                return name, await _consult(client, models[name], get_decision_prompt(name), deliberation.histories[name])
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
                return name, await _rebut(client, models[name], get_decision_prompt(name), deliberation.histories[name], own, others, round_num)
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
    """Yields ("round_start", n), ("vote", name, result), ("rebuttal", name, result),
    ("done", outcome, positions). Outcome is "consensus", "deadlock", or "incomplete"."""
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


def _normalize_option(value: str, options: list[str]) -> str:
    if not value:
        return value
    low = value.strip().lower()
    for opt in options:
        if low == opt.lower():
            return opt
    for opt in options:
        if low in opt.lower() or opt.lower() in low:
            return opt
    return value.strip()


async def _consult_choice(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
    options: list[str],
) -> ChoiceResponse:
    options_block = f"\n\n== OPTIONS FOR THIS QUESTION ==\nPick ONE of: {', '.join(options)}.\nchosen_option must EXACTLY match one of those names."
    schema = ChoiceResponse.model_json_schema()
    response = await client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system + options_block}] + messages,
            "format": schema,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": _ollama_options(temperature=0.7),
        },
        timeout=90.0,
    )
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
    parsed = ChoiceResponse.model_validate_json(_strip_thinking(content))
    parsed.chosen_option = _normalize_option(parsed.chosen_option, options)
    return parsed


async def _rebut_choice(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
    own_position: ChoiceResponse,
    others: dict[str, ChoiceResponse],
    options: list[str],
    round_num: int,
) -> ChoiceRebuttal:
    others_text = "\n\n".join(
        f"{name} picked {r.chosen_option} — {r.reasoning}"
        for name, r in others.items()
    )

    identity_anchor = (
        "REMEMBER: you are speaking ABOUT the user's situation. "
        "Use 'they' / 'the user' / 'their'. Never 'I' / 'my' / 'we'. "
        "The choice belongs to the user, not you."
    )

    options_reminder = (
        f"You must pick from these options: {', '.join(options)}. "
        "final_choice must EXACTLY match one of them."
    )

    if round_num == 2:
        opener = "The other council members have just picked. Here is what they said:"
        closer = (
            "Address them by name. Push back if their pick is wrong from your lens. "
            "1-3 sentences. Then give your final_choice for this round. HOLD YOUR LINE "
            "unless a real argument exposed new information or a flaw. Convergence for its "
            "own sake is failure."
        )
    else:
        opener = (
            f"This is round {round_num} of the deliberation. The other members' "
            "latest picks:"
        )
        closer = (
            "Respond to the latest points. HOLD YOUR LINE unless a real argument "
            "exposed new information or a flaw. 1-3 sentences. Final pick: same as "
            "last round OR updated only if you were genuinely persuaded."
        )

    debate_prompt = f"{identity_anchor}\n\n{options_reminder}\n\n{opener}\n\n{others_text}\n\n{closer}"

    schema = ChoiceRebuttal.model_json_schema()
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
            "keep_alive": KEEP_ALIVE,
            "options": _ollama_options(temperature=0.7),
        },
        timeout=90.0,
    )
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
    parsed = ChoiceRebuttal.model_validate_json(_strip_thinking(content))
    parsed.final_choice = _normalize_option(parsed.final_choice, options)
    return parsed


async def _vote_choice_round(
    deliberation: Deliberation, models: dict[str, str], options: list[str]
) -> AsyncIterator[tuple[str, ChoiceResponse | Exception]]:
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                return name, await _consult_choice(client, models[name], get_choice_prompt(name), deliberation.histories[name], options)
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


async def _debate_choice_round(
    deliberation: Deliberation,
    models: dict[str, str],
    current_positions: dict[str, ChoiceResponse],
    options: list[str],
    round_num: int,
) -> AsyncIterator[tuple[str, ChoiceRebuttal | Exception]]:
    async with httpx.AsyncClient() as client:
        async def rebut(name: str):
            own = current_positions[name]
            others = {n: v for n, v in current_positions.items() if n != name}
            try:
                return name, await _rebut_choice(client, models[name], get_choice_prompt(name), deliberation.histories[name], own, others, options, round_num)
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


def _is_choice_consensus(positions: dict[str, ChoiceResponse]) -> bool:
    choices = [p.chosen_option for p in positions.values()]
    return len(choices) >= 2 and len(set(choices)) == 1


async def iterative_choose(
    deliberation: Deliberation,
    models: dict[str, str],
    options: list[str],
    max_rounds: int = MAX_DELIBERATION_ROUNDS,
) -> AsyncIterator[tuple]:
    """Same event shape as iterative_deliberate but with ChoiceResponse/ChoiceRebuttal."""
    yield ("round_start", 1)
    initial: dict[str, ChoiceResponse | Exception] = {}
    async for name, result in _vote_choice_round(deliberation, models, options):
        initial[name] = result
        yield ("vote", name, result)

    valid: dict[str, ChoiceResponse] = {n: v for n, v in initial.items() if isinstance(v, ChoiceResponse)}
    if len(valid) < 2:
        yield ("done", "incomplete", valid)
        return

    current = dict(valid)
    if _is_choice_consensus(current):
        yield ("done", "consensus", current)
        return

    for round_num in range(2, max_rounds + 1):
        yield ("round_start", round_num)
        async for name, rebuttal in _debate_choice_round(deliberation, models, current, options, round_num):
            yield ("rebuttal", name, rebuttal)
            if isinstance(rebuttal, ChoiceRebuttal):
                prev = current[name]
                current[name] = ChoiceResponse(
                    chosen_option=rebuttal.final_choice,
                    reasoning=prev.reasoning,
                )
        if _is_choice_consensus(current):
            yield ("done", "consensus", current)
            return

    yield ("done", "split", current)


async def _consult_recommend(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
) -> RecommendResponse:
    schema = RecommendResponse.model_json_schema()
    response = await client.post(
        f"{OLLAMA_HOST}/api/chat",
        json={
            "model": model,
            "messages": [{"role": "system", "content": system}] + messages,
            "format": schema,
            "stream": False,
            "keep_alive": KEEP_ALIVE,
            "options": _ollama_options(temperature=0.8, num_predict=800),
        },
        timeout=90.0,
    )
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
    parsed = RecommendResponse.model_validate_json(_strip_thinking(content))
    parsed.recommendation = _clean_recommendation(parsed.recommendation)
    return parsed


async def _rebut_recommend(
    client: httpx.AsyncClient,
    model: str,
    system: str,
    messages: list[dict],
    own_position: RecommendResponse,
    others: dict[str, RecommendResponse],
    round_num: int,
) -> RecommendRebuttal:
    others_text = "\n\n".join(
        f"{name} recommends: {r.recommendation} — {r.reasoning}"
        for name, r in others.items()
    )

    identity_anchor = (
        "REMEMBER: you are speaking ABOUT the user's situation. "
        "Use 'they' / 'the user' / 'their'. Never 'I' / 'my' / 'we'."
    )

    closer = (
        "Address the others by name if you push back. Stay in your lens — your job is NOT to converge "
        "on a single answer; three different concrete recommendations is a valid result. Hold your "
        "recommendation unless a real argument exposed a flaw OR sparked a sharper version. 1-3 sentences. "
        "Then give your final_recommendation: same as before, refined, or replaced. Must remain concrete — "
        "no platitudes."
    )

    if round_num == 2:
        opener = "The other council members have just given their recommendations:"
    else:
        opener = f"This is round {round_num} of the deliberation. Latest recommendations:"

    debate_prompt = f"{identity_anchor}\n\n{opener}\n\n{others_text}\n\n{closer}"

    schema = RecommendRebuttal.model_json_schema()
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
            "keep_alive": KEEP_ALIVE,
            "options": _ollama_options(temperature=0.8, num_predict=800),
        },
        timeout=90.0,
    )
    response.raise_for_status()
    _validate_response(response)
    content = _sanitize_llm_output(response.json()["message"]["content"])
    parsed = RecommendRebuttal.model_validate_json(_strip_thinking(content))
    parsed.final_recommendation = _clean_recommendation(parsed.final_recommendation)
    parsed.response = _strip_persona_prefixes(parsed.response)
    return parsed


async def _vote_recommend_round(
    deliberation: Deliberation, models: dict[str, str]
) -> AsyncIterator[tuple[str, RecommendResponse | Exception]]:
    async with httpx.AsyncClient() as client:
        async def wrap(name: str):
            try:
                return name, await _consult_recommend(client, models[name], get_recommend_prompt(name), deliberation.histories[name])
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


async def _debate_recommend_round(
    deliberation: Deliberation,
    models: dict[str, str],
    current_positions: dict[str, RecommendResponse],
    round_num: int,
) -> AsyncIterator[tuple[str, RecommendRebuttal | Exception]]:
    async with httpx.AsyncClient() as client:
        async def rebut(name: str):
            own = current_positions[name]
            others = {n: v for n, v in current_positions.items() if n != name}
            try:
                return name, await _rebut_recommend(client, models[name], get_recommend_prompt(name), deliberation.histories[name], own, others, round_num)
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


async def iterative_recommend(
    deliberation: Deliberation,
    models: dict[str, str],
) -> AsyncIterator[tuple]:
    """Single round, no rebuttal. Three independent picks from three lenses."""
    yield ("round_start", 1)
    initial: dict[str, RecommendResponse | Exception] = {}
    async for name, result in _vote_recommend_round(deliberation, models):
        initial[name] = result
        yield ("vote", name, result)

    valid: dict[str, RecommendResponse] = {n: v for n, v in initial.items() if isinstance(v, RecommendResponse)}
    outcome = "picks" if len(valid) >= 2 else "incomplete"
    yield ("done", outcome, valid)


def synthesize_recommend(responses: dict[str, RecommendResponse | Exception]) -> str:
    valid = [(n, r) for n, r in responses.items() if isinstance(r, RecommendResponse)]
    n = len(valid)
    if n < 2:
        return f"INCOMPLETE — only {n} council member(s) responded"

    rec_to_names: dict[str, list[str]] = {}
    for name, r in valid:
        rec_to_names.setdefault(r.recommendation.lower().strip(), []).append(name)

    if len(rec_to_names) == 1:
        return f"CONSENSUS — all {n} picked the same direction  →  your call to commit"
    if len(rec_to_names) < n:
        overlaps = [(rec, names) for rec, names in rec_to_names.items() if len(names) > 1]
        if overlaps:
            rec, names = overlaps[0]
            return f"PARTIAL OVERLAP — {len(names)}/{n} agree on one pick  →  your call between {n - len(names) + 1} options"
    return f"{n} DISTINCT PICKS — your call: pick the lens that speaks to you"


def synthesize_choice(
    responses: dict[str, ChoiceResponse | Exception],
    outcome: str,
    options: list[str],
) -> str:
    """Tally choice votes. Returns 'CONSENSUS — Swift (3/3)', 'WINNER — Swift (2/3)',
    or 'TIE — Swift, React Native (1 each)'."""
    valid = {n: r for n, r in responses.items() if isinstance(r, ChoiceResponse)}
    n = len(valid)
    if n < 2:
        return f"INCOMPLETE — only {n} council member(s) responded"

    tally: dict[str, int] = {opt: 0 for opt in options}
    for r in valid.values():
        tally[r.chosen_option] = tally.get(r.chosen_option, 0) + 1

    sorted_tally = sorted(tally.items(), key=lambda kv: (-kv[1], kv[0]))
    top_count = sorted_tally[0][1]
    winners = [opt for opt, c in sorted_tally if c == top_count]
    breakdown = "  ".join(f"{opt}:{c}" for opt, c in sorted_tally if c > 0)

    if len(winners) == 1 and outcome == "consensus":
        return f"CONSENSUS — {winners[0]}  ({breakdown})"
    if len(winners) == 1:
        return f"WINNER — {winners[0]}  ({breakdown})"
    return f"TIE — {' & '.join(winners)}  ({breakdown})  →  your call"




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
