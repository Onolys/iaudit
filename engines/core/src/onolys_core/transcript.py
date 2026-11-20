"""Transcript types (PRD R5). STT interface types live in onolys_core.stt."""

from pydantic import BaseModel

from onolys_core.stt import SttRun


class Turn(BaseModel):
    id: str
    speaker: str | None = None
    text: str
    start_ms: int | None = None
    end_ms: int | None = None
    role: str | None = None
    language: str | None = None


class Transcript(BaseModel):
    turns: list[Turn]
    language: str | None = None
    duration_ms: int | None = None
    # None for text-only transcripts that never went through STT.
    stt_run: SttRun | None = None


class Span(BaseModel):
    """Code-point offsets into the turn text (ADR 0002)."""

    turn_id: str
    start: int
    end: int
