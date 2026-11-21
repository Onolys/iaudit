"""MITI 4.2.1 pack hooks. Pure functions, no I/O. One real hook: `check_input`."""


def check_input(inp, pack_data):
    """Warn when the clinician speaks before any client speech in the coded span.

    A reflection responds to something the client has just said (manual p. 20), so a volley
    that opens the span with no earlier client turn cannot hold a valid reflection. Codes are
    not known at input time, so the structural condition is flagged; the code pass may still
    code such a volley. Returns [] when the client speaks first. Never includes transcript text.
    """
    opening = []
    for rt in inp.turns:
        if rt.role == "other":
            break
        opening.append(rt.turn.id)
    if not opening:
        return []
    return [
        {
            "code": "reflection_before_client_speech",
            "severity": "info",
            "detail": (
                "clinician speech precedes any client speech (turns "
                + ", ".join(opening[:5])
                + (" ..." if len(opening) > 5 else "")
                + "); reflections there cannot respond to the client"
            ),
        }
    ]
