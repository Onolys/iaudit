"""Stage 1: split each assessment section into atomic, verbatim-anchored claims."""

from .models import AtomicClaim, AtomizerOutput, SectionAtoms
from .prompt import Speaker, roster_from_turns
from .stage import atomize_section, atomize_sections

__all__ = [
    "AtomicClaim",
    "AtomizerOutput",
    "SectionAtoms",
    "Speaker",
    "atomize_section",
    "atomize_sections",
    "roster_from_turns",
]
