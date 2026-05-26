"""Journal-backed memory. Searches past deliberations for similar questions
and builds context the council can reference."""

import re
from dataclasses import dataclass

from magi.journal import load_entries

_STOP_WORDS = frozenset({
    "i", "a", "the", "is", "it", "to", "and", "or", "of", "in", "my", "me",
    "should", "do", "have", "be", "will", "can", "would", "could", "this",
    "that", "for", "with", "on", "at", "but", "not", "am", "are", "was",
    "were", "an", "if", "so", "what", "how", "when", "where", "who", "which",
    "been", "has", "had", "than", "too", "very", "just", "about", "im", "ive",
    "dont", "wanna", "gonna", "really", "some", "like", "also", "get",
})


def _tokenize(text: str) -> set[str]:
    words = re.findall(r"\w+", text.lower())
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _similarity(q1: str, q2: str) -> float:
    t1, t2 = _tokenize(q1), _tokenize(q2)
    if not t1 or not t2:
        return 0.0
    return len(t1 & t2) / len(t1 | t2)


@dataclass
class MemoryHit:
    entry_id: str
    question: str
    outcome: str
    synthesis: str
    user_outcome: str | None
    similarity: float
    timestamp: str


MAX_JOURNAL_SCAN = 1000


def search(question: str, threshold: float = 0.25, limit: int = 3) -> list[MemoryHit]:
    entries = load_entries(limit=MAX_JOURNAL_SCAN)
    scored = []
    for entry in entries:
        past_q = entry.get("question", "")
        sim = _similarity(question, past_q)
        if sim >= threshold:
            scored.append(MemoryHit(
                entry_id=entry.get("id", ""),
                question=past_q,
                outcome=entry.get("outcome", ""),
                synthesis=entry.get("synthesis", ""),
                user_outcome=entry.get("user_outcome"),
                similarity=sim,
                timestamp=entry.get("timestamp", "")[:10],
            ))
    scored.sort(key=lambda h: h.similarity, reverse=True)
    return scored[:limit]


MAX_CONTEXT_FIELD_LEN = 200
MAX_OUTCOME_CHARS = 500


def _sanitize_context_field(text: str) -> str:
    text = text[:MAX_CONTEXT_FIELD_LEN].replace("\n", " ").strip()
    return re.sub(r"\[.*?\]", "", text).strip()


def build_context(hits: list[MemoryHit]) -> str:
    if not hits:
        return ""
    lines = ["[COUNCIL MEMORY — the user has asked similar questions before]"]
    for h in hits:
        q = _sanitize_context_field(h.question)
        s = _sanitize_context_field(h.synthesis)
        line = f"- {h.timestamp}: \"{q}\" → {s}"
        if h.user_outcome:
            o = _sanitize_context_field(h.user_outcome)
            line += f" | user later said: \"{o}\""
        lines.append(line)
    lines.append("")
    lines.append("[CURRENT QUESTION]")
    return "\n".join(lines)


@dataclass
class Patterns:
    total_deliberations: int
    outcomes_recorded: int
    top_followed_member: str | None
    top_followed_count: int
    repeat_question: bool
    deadlock_streak: int


def detect_patterns(question: str, entries: list[dict] | None = None) -> Patterns:
    if entries is None:
        entries = load_entries(limit=MAX_JOURNAL_SCAN)

    total = len(entries)
    outcomes_recorded = sum(1 for e in entries if e.get("user_outcome"))
    repeat = any(_similarity(question, e.get("question", "")) >= 0.4 for e in entries)

    deadlock_streak = 0
    for e in entries:
        if e.get("outcome") in ("deadlock", "split"):
            deadlock_streak += 1
        else:
            break

    member_follow_count: dict[str, int] = {}
    for e in entries:
        user_out = e.get("user_outcome", "")
        if not user_out:
            continue
        verdicts = e.get("final_verdicts", {})
        outcome_lower = user_out.lower()
        positive_signals = ("did it", "yes", "went for it", "took it", "agreed",
                           "followed", "no regrets", "glad", "worked out", "good call")
        if any(sig in outcome_lower for sig in positive_signals):
            for name, verdict in verdicts.items():
                if verdict in ("ACCEPT", "YES") or (isinstance(verdict, str) and verdict == e.get("synthesis", "").split("—")[-1].strip().split()[0] if "—" in e.get("synthesis", "") else ""):
                    member_follow_count[name] = member_follow_count.get(name, 0) + 1

    top_member = None
    top_count = 0
    if member_follow_count:
        top_member = max(member_follow_count, key=member_follow_count.get)
        top_count = member_follow_count[top_member]

    return Patterns(
        total_deliberations=total,
        outcomes_recorded=outcomes_recorded,
        top_followed_member=top_member if top_count >= 2 else None,
        top_followed_count=top_count,
        repeat_question=repeat,
        deadlock_streak=deadlock_streak,
    )
