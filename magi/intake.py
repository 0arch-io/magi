"""Question-class intake classifier. Runs once before deliberation to route
the council into the right verdict shape:

    decision    — yes/no question with one decision (default flow)
    choice      — pick between named options
    open        — open-ended request for direction
    prediction  — will X happen / what will happen (interpreted as bet)

Default classifier model is qwen3:4b (already loaded as BALTHASAR's default —
zero extra memory cost). Falls back to `decision` on any classification
failure so we degrade to the original v0.10.x behavior, not crash.
"""

import os
from enum import Enum

import httpx
from pydantic import BaseModel, Field


CLASSIFIER_MODEL = os.environ.get("MAGI_CLASSIFIER_MODEL", "qwen3:4b")
OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


class QuestionClass(str, Enum):
    DECISION = "decision"
    CHOICE = "choice"
    OPEN = "open"
    PREDICTION = "prediction"


class Classification(BaseModel):
    question_class: QuestionClass = Field(
        ...,
        description=(
            "decision: a yes/no question about ONE specific action ('should I take the job?', 'should I open source X?'). "
            "choice: pick between TWO OR MORE named options ('Swift or React Native?', 'Miami or Austin?'). "
            "open: open-ended request for direction with no fixed options ('what should I build?', 'i wanna make something cool'). "
            "prediction: a question about whether something WILL happen ('will my startup hit profitability?', 'am I going to get accepted?')."
        ),
    )
    options: list[str] = Field(
        default_factory=list,
        description=(
            "ONLY for choice questions: the named options the user is choosing between, in the order mentioned. "
            "Each option is a short noun/phrase (e.g. ['Swift', 'React Native']). "
            "Empty list for decision/open/prediction."
        ),
    )


_CLASSIFIER_SYSTEM = """You classify a question into ONE of four shapes so a downstream system knows how to vote on it.

decision    — yes/no question about ONE specific action. Examples: "should I take the job?", "should I move out?", "should we ship this?"
choice      — pick between two or more named options. Examples: "Swift or React Native?", "Miami, Austin, or Denver?", "should I go to MIT or Stanford?"
open        — open-ended ask for direction with no fixed options. Examples: "what should I build?", "i wanna make a new project something cool", "what do I do with my life?"
prediction  — will X happen / forecast. Examples: "will my startup hit profitability?", "am I going to get accepted?", "is the market going to crash?"

For choice questions ONLY, also extract the named options. Keep each option short (a single noun or short phrase). Order them as the user mentioned them.

Edge cases:
- "should I do A or B" — that's CHOICE (options: [A, B]), not decision, even though it starts with 'should'.
- "what should I do, A or B" — also CHOICE (options: [A, B]).
- "should I do anything" / "what should I do" with no options — OPEN, not decision.
- "should I bet on X" — DECISION, not prediction (already framed as a decision).
- Vague pitches like "i wanna build something cool" — OPEN.

Return only the classification. Do not explain.
"""


async def classify(question: str) -> Classification:
    """Classify a user's question. Returns Classification or raises on failure
    (caller should fall back to DECISION on exception)."""
    schema = Classification.model_json_schema()
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{OLLAMA_HOST}/api/chat",
            json={
                "model": CLASSIFIER_MODEL,
                "messages": [
                    {"role": "system", "content": _CLASSIFIER_SYSTEM},
                    {"role": "user", "content": question},
                ],
                "format": schema,
                "stream": False,
                "options": {"temperature": 0.1},  # deterministic-ish — this is a classification, not a creative call
            },
            timeout=30.0,
        )
        response.raise_for_status()
        content = response.json()["message"]["content"]
        return Classification.model_validate_json(content)


async def classify_safe(question: str) -> Classification:
    """Like classify() but never raises. Falls back to DECISION (the original
    behavior) on any error so the deliberation still works if Ollama hiccups."""
    try:
        return await classify(question)
    except Exception:
        return Classification(question_class=QuestionClass.DECISION, options=[])
