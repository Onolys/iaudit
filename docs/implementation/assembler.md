# Assembler

Stage 4: resolve text to positions and enforce the contract. Code: `eaudit/src/eaudit/assembler/`.

**Audience:** maintainers and coding agents.

The models return verbatim text; **code computes every offset**, in code points. Nothing the model writes is trusted to be a position.

1. **Locate** (`locate.py`). Find a segment in its turn or section: exact, then normalised (case, punctuation, whitespace), then fuzzy (`fuzzy_threshold`, `fuzzy_min_len`), nearest to a hint. Multi-segment excerpts merge into one cross-turn span only when the turns are consecutive and the seams are whole.
2. **Claims** (`claims.py`). Resolve each claim, then apply the overlap policy per section: nested claims drop the outer, identical spans keep the more severe verdict, partial overlaps keep the more severe and trim or drop the other (`overlap_trim`). Ids `c1..cN` follow document order.
3. **Evidence** (`evidence.py`). Resolve excerpts, drop unmatched ones, merge duplicates, assign final ids.
4. **Repair** (`repair.py`). Enforce the verdict rules: for example, `supported` needs a supporting excerpt, `contradicted` needs a contradicting one, `partially_supported` needs a concern, `out_of_scope` carries no evidence. A change of verdict swaps in a fixed explanation and adds an `other` warning.
5. **Copy guard** (`copycheck.py`). Assessor text must be written, not copied: quoted spans of four or more words, timestamps, notes that are substrings of a turn, and runs of `copy_ngram` words that the assessment does not itself contain are removed, falling back to fixed text.
6. **Warnings and status** (`warnings.py`). Section, claim and aggregate warnings with fixed messages; `partial` iff a section was not processed.
7. **Final validation** (`validate.py`). An independent rules check plus the response schema. Offending claims are quarantined once; any other failure raises `AssemblyError` (a 500). The service never ships an invalid reply.
