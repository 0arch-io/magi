import asyncio
from enum import Enum

from anthropic import AsyncAnthropic
from pydantic import BaseModel

from magi.personas import PERSONAS


class Verdict(str, Enum):
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"
    CONDITIONAL = "CONDITIONAL"


class PersonaResponse(BaseModel):
    verdict: Verdict
    reasoning: str
    key_concern: str


async def _consult(client: AsyncAnthropic, model: str, name: str, system: str, question: str) -> PersonaResponse:
    response = await client.messages.parse(
        model=model,
        max_tokens=8192,
        thinking={"type": "adaptive"},
        system=system,
        messages=[{"role": "user", "content": question}],
        output_format=PersonaResponse,
    )
    return response.parsed_output


async def consult_all(question: str, model: str) -> dict[str, PersonaResponse | Exception]:
    async with AsyncAnthropic() as client:
        tasks = [
            _consult(client, model, name, system, question)
            for name, system in PERSONAS.items()
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)
    return dict(zip(PERSONAS.keys(), results))


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
