"""Shared interface types for Onolys engines. Must never import eaudit, paudit or api."""

from onolys_core.engine import Engine, EngineResult, PackRef, RunContext
from onolys_core.errors import InputError, OnolysError, PackError
from onolys_core.stt import AudioRef, SttAdapter, SttParams, SttRun, Word
from onolys_core.transcript import Span, Transcript, Turn

__all__ = [
    "AudioRef", "Engine", "EngineResult", "InputError", "OnolysError", "PackError",
    "PackRef", "RunContext", "Span", "SttAdapter", "SttParams", "SttRun", "Transcript",
    "Turn", "Word",
]
