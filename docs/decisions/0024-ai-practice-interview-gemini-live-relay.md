# 0024. AI practice interview: Gemini Live via server-side relay

**Audience:** contributors.

**Status:** accepted. Reference: [public-api.md, AI practice interviews](../reference/public-api.md#ai-practice-interviews). Design: [SP10 PRD](../agent_files/feat-miti-platform-20261120-0153/10-ai-interview/PRD.md). Measurements: [spike RESULTS](../agent_files/feat-miti-platform-20261120-0153/10-ai-interview/spike/RESULTS.md).

**Context.** A clinician can practise a mock motivational-interviewing session against an AI client that speaks, then send the recording through the normal evaluation path. The client persona carries hidden information the clinician must earn; it must not reach the browser.

**Decision.**

- **D15 Gemini is an owner-approved exception to the Claude-only LLM rule, for the client voice only.** Real-time voice needs a native-audio live model. All rating and evaluation work stays on Claude.
- **Server-side relay, not browser-direct.** The browser sends mic audio to a relay; the relay owns the persona prompt, `hidden_info`, response rules and the clock, and talks to Vertex. A browser-direct session would put the persona in the client. The relay also enforces the 600 s cap, the 480 s warning and resumption.
- **Separate Cloud Run service `onolys-voice-{env}`.** Hosting rewrites time out at 60 s, so the browser connects straight to the service's `run.app` `wss` URL; the CSP `connect-src` allows exactly that host. The voice service account holds only `aiplatform.user` plus Firestore.
- **Auth in the first frame.** Browsers cannot set headers on a WebSocket, so the first message is `{type:"auth", id_token}`; the relay also checks `Origin`. Close codes 4401, 4403, 4404, 4409.
- **Model `gemini-3.8-live`, configurable.** The owner's live sessions measured $0.039 per minute (3 sessions of 76-199 s; cost per minute rises with session length because context is re-billed each turn, so a 10-minute session may reach about $0.11 per minute) and a median reply of 1.34 s (p90 1.48 s, n=32); the older native-audio model (median 1.89 s live, one upstream failure) was dearer and worse at holding the role. The model id is config, not code.
- **Voices are user-selectable (D16)** from the voices the service exposes in `GET /scenarios`; the scenario's own voice is the default and the user can pick any allowed voice.
- **Resumption.** The relay stores the Gemini resumption handle: an upstream drop or `GoAway` reopens silently; a dropped client reconnects within 60 s and the elapsed time carries over.

**Consequences.** One more service and its image to deploy; Gemini is the only non-Claude model and is isolated behind `onolys_core.voice`; the persona never appears in a response, frame or log line (tests scan for it). Live items (10-minute staging session, forced 20 s drop, browser pitch checks) are recorded in the SP10 acceptance mapping.
