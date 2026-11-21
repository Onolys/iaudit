"""Static check: admin_enabled is a per-env map (staging on, prod off); no bare boolean use remains."""
import pathlib
import re

INFRA = pathlib.Path(__file__).parent.parent
VARS = (INFRA / "variables.tf").read_text()
TF = {p.name: p.read_text() for p in INFRA.glob("*.tf")}


def test_variable_is_map_staging_on_prod_off():
    m = re.search(r'variable "admin_enabled" \{(.*?)\n\}', VARS, re.S)
    assert m
    b = m.group(1)
    assert "map(bool)" in b
    assert re.search(r"staging\s*=\s*true", b) and re.search(r"prod\s*=\s*false", b)
    assert "validation" in b


def test_no_bare_boolean_use():
    for name, text in TF.items():
        if name == "variables.tf":
            continue
        for line in text.splitlines():
            if "var.admin_enabled" in line:
                assert re.search(r'var\.admin_enabled\["(staging|prod)"\]', line), (name, line)
                assert not re.search(r"var\.admin_enabled(?!\[)", line), (name, line)


def test_modules_get_their_own_env_flag():
    main = TF["main.tf"]
    for env in ("staging", "prod"):
        blk = main[main.index(f'module "{env}"'):]
        blk = blk[: blk.index("\n}")]
        assert f'admin_enabled            = var.admin_enabled["{env}"]' in blk, env
