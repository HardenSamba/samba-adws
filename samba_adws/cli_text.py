"""Rendering an answer for a person, which is not who this command is for."""

from typing import Any, List, Mapping

# How much of one attribute value a listing shows before it stops. A directory
# carries values that are longer than a terminal, and a page of objects is a
# spot check: a value nobody asked for by name must not bury the next object.
WIDTH = 60


# One attribute value, whole.
def value(held: Any) -> str:
    return ", ".join(str(each) for each in held) if isinstance(held, list) else str(held)


# The same, trimmed to something a line can hold.
#
# Only a listing trims. A document that is itself the answer prints whole:
# `naming-context` returns a distinguished name the operator pastes into
# `--base`, and an ellipsised one is worse than none, because it looks usable.
def clamped(held: Any) -> str:
    text = value(held)
    return text if len(text) <= WIDTH else f"{text[:WIDTH]}…"


# One object of a listing, as indented lines under its own heading.
def entry(obj: Mapping[str, Any]) -> List[str]:
    return [f"  {name}: {clamped(held)}" for name, held in sorted(obj.items())]


# The whole answer, as text. A page of objects becomes a block each; anything
# else is a document whose values are the answer, and is printed unabridged.
def render(payload: Mapping[str, Any]) -> str:
    if "objects" not in payload:
        return "\n".join(f"{name}: {value(held)}" for name, held in payload.items())
    lines: List[str] = []
    for obj in payload["objects"]:
        lines += entry(obj) + [""]
    return "\n".join(lines + [f"cursor: {payload.get('cursor', '')!r}"])
