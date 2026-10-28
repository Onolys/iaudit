"""Prep LLM prompt: act definitions and two inline examples from the rule table.

The examples are invented, not taken from any eval set (see tests/test_prompt_leakage.py).
The prompt names tiers only; model ids never appear here.
"""

from .models import Act, IndexedTurn

EXAMPLES = [
    "Turn: 'Tell me about last week.' -> acts: question. "
    "Turn: 'Sorry, I meant Tuesday.' -> acts: correction.",
    "Turn: 'Suppose the bus never came.' -> acts: hypothetical. "
    "Turn: 'If the bus is late I walk.' -> acts: none (habitual, not hypothetical).",
]

SYSTEM = (
    "You tag dialogue acts in an interview transcript. Reply with the JSON object only.\n"
    "Acts: question (asks for information), correction (the speaker revises their own earlier "
    "statement), hypothetical (an imagined or conditional scenario, not a habit).\n"
    "Tag only the turns listed after TAG:. Other turns are read-only context. For each listed "
    "turn return the acts that apply, or an empty list. Never return other turns.\n"
    "Examples:\n" + "\n".join(EXAMPLES)
)


def render_user(
    window: list[IndexedTurn], requested: list[int], kinds: dict[int, frozenset[Act]]
) -> str:
    lines = [f"TAG: {', '.join(str(i) for i in requested)}"]
    for t in window:
        mark = " <-" if t.index in requested else ""
        lines.append(f"[{t.index}] {t.speaker or "unknown"}: {t.text}{mark}")
    return "\n".join(lines)
