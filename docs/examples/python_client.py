"""Send the contract's worked example to the backend and print each verdict.

    python docs/examples/python_client.py [http://localhost:8000]

Standard library only. Offsets count code points, which is what Python string slicing uses, so a
claim's text is `section_text[start:end]`. The example is fictional.
"""

import json
import sys
import urllib.request
from pathlib import Path

REQUEST = Path(__file__).resolve().parents[1] / "contracts" / "examples" / "request.json"


def audit(base_url: str, request: dict) -> dict:
    http = urllib.request.Request(
        base_url.rstrip("/") + "/v1/audit",
        data=json.dumps(request).encode(),
        headers={"content-type": "application/json"},
    )
    with urllib.request.urlopen(http, timeout=130) as resp:
        return json.load(resp)


def main(base_url: str) -> None:
    request = json.loads(REQUEST.read_text(encoding="utf-8"))
    reply = audit(base_url, request)
    sections = [s["text"] for s in request["assessment"]]
    for claim in reply["claims"]:
        start, end = claim["span"]["start"], claim["span"]["end"]
        text = sections[start["index"]][start["char"] : end["char"]]
        print(f"{claim['verdict']:<22} {text}")
        for concern in claim["concerns"]:
            print(f"    concern: {concern['type']}")
    print(f"status: {reply['status']}, claims: {len(reply['claims'])}")
    for warning in reply["warnings"]:
        print(f"warning: {warning['code']}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000")
