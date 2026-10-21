"""Check launch configuration without starting any of the development services."""

import subprocess

from iaudit_eval.paths import repo_root


def test_dev_script_eval_launch_disables_access_logs():
    # Removing the flag must fail here: raw paths/query text may contain sensitive item data.
    script = (repo_root() / "scripts" / "dev.sh").read_text(encoding="utf-8")
    statements = script.replace("\\\n", "").splitlines()
    launches = [line for line in statements if line.startswith("launch eval ")]
    assert len(launches) == 1
    # Evaluate the real launch statement with a capture-only function, never a server command.
    captured = subprocess.run(
        [
            "bash",
            "-c",
            'launch() { printf "%s\\0" "$@"; }; '
            "BACKEND_PORT=8000; EVAL_PORT=8100; " + launches[0],
        ],
        check=True,
        capture_output=True,
        timeout=5,
    )
    args = captured.stdout.decode().rstrip("\0").split("\0")
    assert args[:2] == ["eval", "eval"]
    app_index = args.index("iaudit_eval.server.app:app")
    assert args[app_index - 3 : app_index] == ["uv", "run", "uvicorn"]
    assert "--no-access-log" in args[app_index + 1 :]
