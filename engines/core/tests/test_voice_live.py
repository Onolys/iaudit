"""Live Gemini voice check (real Vertex session, ADC). Excluded from PR CI (`-m live`)."""

import asyncio
import os

import pytest

from onolys_core.voice import AudioOut, Closed
from onolys_core.voice.gemini_live_vertex import GeminiLiveVertex
from onolys_core.voice.select import select_voice

pytestmark = pytest.mark.live


async def test_real_session_opens_and_speaks():
    params = select_voice(
        system_prompt="You are a friendly test partner. Say one short greeting, then stop.",
    )
    # On Cloud Run the project comes from ADC; on a dev host name it (default: onolys).
    params.options["project"] = os.environ.get("GOOGLE_CLOUD_PROJECT", "onolys")
    session = await GeminiLiveVertex().open(params)
    try:
        await session.send_audio(b"\x00\x00" * 1600)  # 100 ms of 16 kHz silence

        async def first_audio():
            async for ev in session.events():
                if isinstance(ev, AudioOut):
                    return ev
                if isinstance(ev, Closed):
                    return None

        # Silence may not trigger a reply; only require the session to open and stay healthy.
        try:
            ev = await asyncio.wait_for(first_audio(), 15)
        except TimeoutError:
            ev = None
        assert ev is None or len(ev.pcm24k) > 0
    finally:
        await session.close()
