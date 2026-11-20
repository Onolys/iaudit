"""Transcript types (PRD R5). STT interface types live in onolys_core.stt."""

import re
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel

from onolys_core.stt import SttRun

_MMSS = re.compile(r"(\d+):([0-5]\d)")


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

    def to_eaudit_turns(self) -> list[dict[str, Any]]:
        """eaudit request `transcript` items (ms -> "mm:ss"); None fields are omitted."""
        out = []
        for t in self.turns:
            d: dict[str, Any] = {"id": t.id, "speaker": t.speaker, "role": t.role, "text": t.text}
            if t.start_ms is not None:
                secs = t.start_ms // 1000
                d["timestamp"] = f"{secs // 60:02d}:{secs % 60:02d}"
            out.append({k: v for k, v in d.items() if v is not None})
        return out

    @classmethod
    def from_eaudit_turns(cls, turns: Iterable[Any], **kwargs: Any) -> "Transcript":
        """Build from eaudit turns (dicts or models). Only a literal "mm:ss" timestamp becomes
        `start_ms`; anything else is left unset (never inferred)."""
        out = []
        for raw in turns:
            d = raw if isinstance(raw, dict) else raw.model_dump(mode="json")
            m = _MMSS.fullmatch(str(d.get("timestamp") or ""))
            out.append(
                Turn(
                    id=d["id"],
                    speaker=d.get("speaker"),
                    text=d["text"],
                    role=d.get("role"),
                    start_ms=(int(m[1]) * 60 + int(m[2])) * 1000 if m else None,
                )
            )
        return cls(turns=out, **kwargs)


class Span(BaseModel):
    """Code-point offsets into the turn text (ADR 0002)."""

    turn_id: str
    start: int
    end: int
