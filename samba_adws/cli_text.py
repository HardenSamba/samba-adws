"""Rendering an answer for a person, which is not who this command is for."""

from typing import Any, List, Mapping

# How much of one attribute value a listing shows before it stops. A directory
# carries values that are longer than a terminal, and a probe or a spot check
# is not the place to read them.
WIDTH = 60


# One attribute, trimmed to something a line can hold.
def value(held: Any) -> str:
    text = ", ".join(str(each) for each in held) if isinstance(held, list) else str(held)
    return text if len(text) <= WIDTH else f"{text[:WIDTH]}…"


# One object, as indented lines under its own heading.
def entry(obj: Mapping[str, Any]) -> List[str]:
    return [f"  {name}: {value(held)}" for name, held in sorted(obj.items())]


# The whole answer, as text. A page of objects becomes a block each; anything
# else becomes its keys, which is what `status` is.
def render(payload: Mapping[str, Any]) -> str:
    if "objects" not in payload:
        return "\n".join(f"{name}: {value(held)}" for name, held in payload.items())
    lines: List[str] = []
    for obj in payload["objects"]:
        lines += entry(obj) + [""]
    return "\n".join(lines + [f"cursor: {payload.get('cursor', '')!r}"])
