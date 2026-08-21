"""AddRequest / ModifyRequest body rendering for the write operations."""

import html
from typing import Mapping, Sequence, Tuple

# Attributes that locate an object rather than describe it; kept ad:-qualified.
_ROUTING = frozenset((
    "relativedistinguishedname", "container-hierarchy-parent", "distinguishedname",
))


# Splits a distinguished name into its leftmost RDN and its parent DN.
def split_dn(dn: str) -> Tuple[str, str]:
    escaped = False
    for index, char in enumerate(dn):
        if escaped:
            escaped = False
        elif char == "\\":
            escaped = True
        elif char == ",":
            return dn[:index].strip(), dn[index + 1:].strip()
    return dn.strip(), ""


# Qualifies an attribute name: routing attributes are ad:, data ones addata:.
def _qualified(name: str) -> str:
    if name.lower() in _ROUTING:
        return f"ad:{name}"
    return f"addata:{html.escape(name)}"


# Renders one attribute as an AttributeTypeAndValue or a replace Change node.
def _node(name: str, values: Sequence[str], change: bool) -> str:
    rendered = "".join(f"<ad:value>{html.escape(v)}</ad:value>" for v in values)
    inner = (
        f'<da:AttributeType>{_qualified(name)}</da:AttributeType>'
        f'<da:AttributeValue>{rendered}</da:AttributeValue>'
    )
    if change:
        return f'<da:Change Operation="replace">{inner}</da:Change>'
    return f'<da:AttributeTypeAndValue>{inner}</da:AttributeTypeAndValue>'


# Wraps attribute nodes in an AddRequest or a ModifyRequest body element.
def request_body(entries: Mapping[str, Sequence[str]], change: bool) -> str:
    nodes = "".join(_node(name, values, change) for name, values in entries.items())
    if change:
        return f'<da:ModifyRequest>{nodes}</da:ModifyRequest>'
    return f'<da:AddRequest>{nodes}</da:AddRequest>'
