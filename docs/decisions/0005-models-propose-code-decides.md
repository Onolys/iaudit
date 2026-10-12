# 0005. Models propose, code decides

**Audience:** contributors.

**Status:** accepted.

**Context.** A single model asked for a verdict gives plausible but unverifiable answers, and its explanation can invent quotations or positions.

**Decision.** The audit is staged: prep (rules), atomize, link and check (models that propose and observe), then a code assembler. Models never write offsets, ids, verdicts or final explanations. Code derives the verdict from observations and writes explanations from fixed templates.

**Alternatives.** One model call per claim that returns the whole result.

**Consequences.** Every verdict traces to observations and a decision table. The price is more stages and more code to keep consistent.
