"""Independent span bounds check (rule 1). Does not trust the resolvers that built the span."""


def span_in_bounds(span: dict, lengths: list[int], *, single_index: bool = False) -> bool:
    s, e = span["start"], span["end"]
    si, sc, ei, ec = s["index"], s["char"], e["index"], e["char"]
    if not (0 <= si <= ei < len(lengths)):
        return False
    if single_index and si != ei:
        return False
    if not 0 <= sc < lengths[si]:  # a start pointer must be inside the item
        return False
    if not 0 <= ec <= lengths[ei]:
        return False
    if si == ei:
        return sc < ec
    return ec > 0  # a cross-turn span must not end at char 0
