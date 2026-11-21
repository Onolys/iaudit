"""changes.sh's DEPS map must match the pyproject dependencies of the workspace packages."""

import re
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = (ROOT / "scripts/ci/changes.sh").read_text()


def _array(name: str) -> list[str]:
    m = re.search(rf"^{name}=\(\n(.*?)^\)", SCRIPT, re.S | re.M)
    assert m, f"{name} array not found in changes.sh"
    return re.findall(r'"([^"]+)"', m.group(1))


def _req_name(req: str) -> str:
    return re.split(r"[\[<>=!~; ]", req.strip(), maxsplit=1)[0]


def test_deps_map_matches_pyproject_dependencies() -> None:
    packages = [e.split(":") for e in _array("PACKAGES")]
    project_of: dict[str, str] = {}  # CI name -> pyproject project name
    deps_of: dict[str, list[str]] = {}
    for name, d, kind in packages:
        if kind != "python" or not (ROOT / d / "pyproject.toml").exists():
            continue
        proj = tomllib.loads((ROOT / d / "pyproject.toml").read_text())["project"]
        project_of[name] = proj["name"]
        deps_of[name] = [_req_name(r) for r in proj.get("dependencies", [])]
    ci_name = {v: k for k, v in project_of.items()}
    expected = {
        n: sorted(ci_name[d] for d in deps if d in ci_name)
        for n, deps in deps_of.items()
        if any(d in ci_name for d in deps)
    }
    actual = {}
    for entry in _array("DEPS"):
        name, deps = entry.split(":")
        actual[name] = sorted(deps.split())
    assert actual == expected


if __name__ == "__main__":
    test_deps_map_matches_pyproject_dependencies()
    print("ok   changes.sh DEPS map matches pyproject dependencies")
