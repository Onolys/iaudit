"""R6/D6: tone rules enforced in code. The banned list and every static report string live in
the pack (`pack.yaml > evaluation.tone.banned`, `report.yaml`); this module only applies them.
A violation names the rule, never the offending text."""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from paudit.pack import Pack


class ReportConfigError(ValueError):
    """A malformed tone spec or `report.yaml` (message names the field)."""


@dataclass(frozen=True)
class ToneViolation:
    kind: str  # "phrase" | "pattern"
    rule: str


@dataclass(frozen=True)
class ToneRules:
    phrases: tuple[str, ...]
    patterns: tuple[str, ...]

    @classmethod
    def from_spec(cls, spec: Any) -> "ToneRules":
        """`spec` is `{phrases: [str], patterns: [regex]}` (both optional)."""
        if not isinstance(spec, dict):
            raise ReportConfigError("evaluation.tone.banned must be a mapping")
        out: dict[str, tuple[str, ...]] = {}
        for key in ("phrases", "patterns"):
            val = spec.get(key, [])
            if not isinstance(val, list) or not all(isinstance(x, str) and x.strip() for x in val):
                raise ReportConfigError(f"evaluation.tone.banned.{key} must be a list of strings")
            out[key] = tuple(x.strip() for x in val)
        for p in out["patterns"]:
            try:
                re.compile(p)
            except re.error as exc:
                raise ReportConfigError(
                    f"evaluation.tone.banned.patterns: bad regex {p!r}: {exc}") from exc
        return cls(out["phrases"], out["patterns"])

    def lint(self, text: str) -> list[ToneViolation]:
        """Violations in `text` (empty = clean). Case-insensitive; phrases match whole words."""
        hits = [ToneViolation("phrase", ph) for ph in self.phrases
                if re.search(rf"(?<!\w){re.escape(ph)}(?!\w)", text, re.I)]
        hits += [ToneViolation("pattern", p) for p in self.patterns if re.search(p, text, re.I)]
        return hits


def tone_rules(pack: Pack) -> ToneRules:
    tone = (pack.data.get("evaluation") or {}).get("tone")
    if not isinstance(tone, dict) or "banned" not in tone:
        raise ReportConfigError("pack.yaml: evaluation.tone.banned is missing")
    return ToneRules.from_spec(tone["banned"])


@dataclass(frozen=True)
class SectionCfg:
    id: str
    label: str
    items: list[str] | None
    enabled: bool


@dataclass(frozen=True)
class MethodCfg:
    statement: str
    limits: list[str]
    citation: str


@dataclass(frozen=True)
class ReportConfig:
    headline: str
    max_instances_shown: int
    method: MethodCfg
    sections: list[SectionCfg]

    def layout(self) -> list[dict[str, Any]]:
        """Ordered `layout` entries for the report (disabled sections left out)."""
        return [{"section": s.id, "title": s.label,
                 **({"items": s.items} if s.items is not None else {})}
                for s in self.sections if s.enabled]

    def static_strings(self) -> list[str]:
        """Every human-readable string the pack puts in the report (for the tone lint)."""
        return [self.headline, self.method.statement, *self.method.limits, self.method.citation,
                *(s.label for s in self.sections)]


def _str(d: dict, key: str, where: str) -> str:
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ReportConfigError(f"report.yaml: {where}{key} must be a non-empty string")
    return v


def parse_report_config(data: Any) -> ReportConfig:
    if not isinstance(data, dict):
        raise ReportConfigError("report.yaml must be a mapping")
    headline = _str(data, "headline", "")
    n = data.get("max_instances_shown")
    if not isinstance(n, int) or isinstance(n, bool) or n < 1:
        raise ReportConfigError("report.yaml: max_instances_shown must be an integer >= 1")
    m = data.get("method")
    if not isinstance(m, dict):
        raise ReportConfigError("report.yaml: method must be a mapping")
    limits = m.get("limits")
    if not (isinstance(limits, list) and limits
            and all(isinstance(x, str) and x.strip() for x in limits)):
        raise ReportConfigError("report.yaml: method.limits must be a non-empty list of strings")
    method = MethodCfg(_str(m, "statement", "method."), limits, _str(m, "citation", "method."))
    raw = data.get("sections")
    if not isinstance(raw, list) or not raw:
        raise ReportConfigError("report.yaml: sections must be a non-empty list")
    sections: list[SectionCfg] = []
    for i, s in enumerate(raw):
        if not isinstance(s, dict):
            raise ReportConfigError(f"report.yaml: sections[{i}] must be a mapping")
        sid = _str(s, "id", f"sections[{i}].")
        label = _str(s, "label", f"sections[{i}].")
        if any(x.id == sid for x in sections):
            raise ReportConfigError(f"report.yaml: duplicate section id {sid!r}")
        items = s.get("items")
        if items is not None and not (
                isinstance(items, list) and all(isinstance(x, str) for x in items)):
            raise ReportConfigError(f"report.yaml: sections[{i}].items must be a list of strings")
        enabled = s.get("enabled", True)
        if not isinstance(enabled, bool):
            raise ReportConfigError(f"report.yaml: sections[{i}].enabled must be true or false")
        sections.append(SectionCfg(sid, label, items, enabled))
    return ReportConfig(headline, n, method, sections)


def load_report_config(path: str | Path) -> ReportConfig:
    p = Path(path)
    if not p.is_file():
        raise ReportConfigError(f"report.yaml not found: {p}")
    try:
        data = yaml.safe_load(p.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ReportConfigError(f"report.yaml is not valid YAML: {exc}") from exc
    return parse_report_config(data)
# scratch CI skip proof (SP00 T6); throwaway, not merged
