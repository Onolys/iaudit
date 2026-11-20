"""Protocol-pack loader: resolve, schema-validate, parity-check, hash. Errors are `PackError`
and are raised at load only, never at run time."""

import json
import os
import re
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from onolys_core import PackError, PackRef
from onolys_core.run_info import PackFacts, hash_files

from paudit.formula import FormulaError, names

PACK_FORMAT = "0.0.1"
PROTOCOLS_ENV = "PAUDIT_PROTOCOLS_DIR"
PROMPT_FILES = ("code_system.md", "code_fewshot.json", "globals_system.md", "globals_fewshot.json")
_REF = re.compile(r"^(?P<id>[a-z][a-z0-9_-]*)@(?P<version>[0-9A-Za-z][0-9A-Za-z._+-]*)$")


def _schema_path() -> Path:
    here = Path(__file__).resolve()
    for cand in (here.parent / "schemas", here.parents[2] / "schemas"):
        if (cand / "pack.schema.json").is_file():
            return cand / "pack.schema.json"
    raise PackError("pack.schema.json not found")


@cache
def pack_schema() -> dict[str, Any]:
    return json.loads(_schema_path().read_text())


def default_protocols_dir() -> Path:
    env = os.environ.get(PROTOCOLS_ENV)
    return Path(env) if env else Path(__file__).resolve().parents[4] / "protocols"


@dataclass(frozen=True)
class Pack:
    root: Path
    data: dict[str, Any]
    rating_schema: dict[str, Any]
    report: dict[str, Any]
    pack_hash: str

    @property
    def id(self) -> str:
        return self.data["id"]

    @property
    def version(self) -> str:
        return self.data["version"]

    @property
    def pack_format(self) -> str:
        return self.data["pack_format"]

    @property
    def items(self) -> list[dict[str, Any]]:
        return self.data["items"]

    @property
    def rules_path(self) -> Path | None:
        p = self.root / "rules.py"
        return p if p.is_file() else None

    @property
    def prompt_paths(self) -> list[Path]:
        return [self.root / "prompts" / n for n in PROMPT_FILES]

    def ref(self) -> PackRef:
        return PackRef(id=self.id, version=self.version, path=str(self.root))

    def facts(self) -> PackFacts:
        return PackFacts(id=self.id, version=self.version, hash=self.pack_hash)


def load_pack(ref: str | Path, protocols_dir: str | Path | None = None) -> Pack:
    """Load `id@version` from `protocols_dir/<id>-<version>/` or a pack directory path."""
    root = _resolve(ref, protocols_dir)
    data = _read_yaml(root / "pack.yaml")
    _validate_schema(data, root)
    rating = _read_json(root / "rating.schema.json")
    report = _read_yaml(root / "report.yaml", what="report.yaml")
    _check_parity(root, data, rating, report)
    if m := _REF.match(str(ref)):
        if (m["id"], m["version"]) != (data["id"], data["version"]):
            found = f"{data['id']}@{data['version']}"
            raise PackError(f"{ref}: pack.yaml says {found} (id/version mismatch)")
    return Pack(root, data, rating, report, hash_files(_hash_paths(root)))


def _resolve(ref: str | Path, protocols_dir: str | Path | None) -> Path:
    if isinstance(ref, Path) or not _REF.match(ref):
        root = Path(ref)
    else:
        m = _REF.match(ref)
        base = Path(protocols_dir) if protocols_dir is not None else default_protocols_dir()
        root = base / f"{m['id']}-{m['version']}"
    if not root.is_dir():
        raise PackError(f"pack not found: {ref} (looked at {root})")
    return root


def _read_yaml(path: Path, what: str = "pack.yaml") -> Any:
    try:
        return yaml.safe_load(path.read_text())
    except OSError as exc:
        raise PackError(f"{what}: cannot read {path}: {exc.strerror}") from exc
    except yaml.YAMLError as exc:
        raise PackError(f"{what}: invalid YAML in {path}") from exc


def _read_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text())
    except OSError as exc:
        raise PackError(f"rating schema: cannot read {path}: {exc.strerror}") from exc
    except json.JSONDecodeError as exc:
        raise PackError(f"rating schema: invalid JSON in {path}") from exc
    if not isinstance(data, dict):
        raise PackError("rating schema: must be a JSON object")
    return data


def _validate_schema(data: Any, root: Path) -> None:
    validator = Draft202012Validator(pack_schema())
    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    if errors:
        where = "/".join(str(p) for p in errors[0].absolute_path) or "<root>"
        msg = errors[0].message[:200]
        raise PackError(f"{root.name}/pack.yaml violates pack schema at {where}: {msg}")


def _hash_paths(root: Path) -> list[Path]:
    """Files covered by pack_hash, in a fixed order. Fixtures are deliberately not covered."""
    paths = [root / "pack.yaml"]
    if (root / "rules.py").is_file():
        paths.append(root / "rules.py")
    paths += [root / "rating.schema.json"]
    paths += sorted((root / "prompts").glob("*")) if (root / "prompts").is_dir() else []
    paths.append(root / "report.yaml")
    return paths


def _rating_keys(rating: dict[str, Any], section: str) -> set[str]:
    sec = (rating.get("properties") or {}).get(section) or {}
    return set((sec.get("properties") or {}).keys())


def _check_parity(root: Path, data: dict[str, Any], rating: dict[str, Any], report: Any) -> None:
    items = data["items"]
    ids = [i["id"] for i in items]
    summary_ids = [s["id"] for s in data.get("summaries", [])]
    dup = sorted({x for x in ids + summary_ids if (ids + summary_ids).count(x) > 1})
    if dup:
        raise PackError(f"duplicate ids across items/summaries: {dup}")
    known = set(ids)

    for i in items:
        if i["kind"] == "global":
            s = i["scale"]
            if not s["min"] <= s["default"] <= s["max"]:
                raise PackError(f"item {i['id']}: scale default outside min..max")

    for section, kind in (("globals", "global"), ("counts", "count")):
        want = {i["id"] for i in items if i["kind"] == kind}
        got = _rating_keys(rating, section)
        if want != got:
            raise PackError(
                f"rating schema '{section}' keys differ from pack items: "
                f"missing {sorted(want - got)}, extra {sorted(got - want)}"
            )

    for rule in data.get("rules", []):
        codes = list(rule.get("codes", []))
        if rule["kind"] == "max_per_unit" and rule["code"] != "any":
            codes.append(rule["code"])
        unknown = sorted(set(codes) - known)
        if unknown:
            raise PackError(f"rule {rule['kind']}: unknown item ids {unknown}")
        if rule["kind"] == "exclusive_group":
            extra = sorted(set(rule.get("precedence", [])) - set(rule["codes"]))
            if extra:
                raise PackError(f"exclusive_group precedence {extra} not a subset of its codes")

    for s in data.get("summaries", []):
        try:
            unknown = sorted(names(s["expr"]) - known)
        except FormulaError as exc:
            raise PackError(f"summary {s['id']}: bad formula: {exc}") from exc
        if unknown:
            raise PackError(f"summary {s['id']}: formula references unknown ids {unknown}")

    unknown = sorted(set(data.get("compare", {})) - known)
    if unknown:
        raise PackError(f"compare references unknown item ids {unknown}")

    for name in PROMPT_FILES:
        if not (root / "prompts" / name).is_file():
            raise PackError(f"prompt file missing: prompts/{name}")

    referenced = _report_ids(report)
    unknown = sorted(referenced - known - set(summary_ids))
    if unknown:
        raise PackError(f"report.yaml references unknown ids {unknown}")


def _report_ids(report: Any) -> set[str]:
    """Ids a report layout lists: `sections[].items[]` (item or summary ids)."""
    if not isinstance(report, dict):
        raise PackError("report.yaml must be a mapping with a 'sections' list")
    out: set[str] = set()
    for sec in report.get("sections", []):
        listed = sec.get("items", []) if isinstance(sec, dict) else []
        out.update(x for x in listed if isinstance(x, str))
    return out
