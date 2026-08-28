"""AddRequest and ModifyRequest body rendering for the write operations.

**The client decides `ad:` versus `addata:`, not the caller.** An attribute that
locates an object — its relative name, its parent — belongs to the Active
Directory namespace; one that describes it belongs to the data namespace. A
caller passing `sn` should not have to know that, and a caller passing
`ad:relativeDistinguishedName` as a literal string would be spelling this
module's job into its own.

**Every value and every caller-supplied name is escaped where it enters the
document.** These are strings an administrator typed: an unescaped ampersand
produces a request the server cannot parse, and an unescaped angle bracket
produces one it parses differently from what was meant.
"""

import html
from typing import Mapping, Sequence

# Attributes that locate an object rather than describe it; kept ad:-qualified.
_ROUTING = frozenset((
    "relativedistinguishedname", "container-hierarchy-parent", "distinguishedname",
))


# Qualifies an attribute name: routing attributes are ad:, data ones addata:.
def _qualified(name: str) -> str:
    if name.lower() in _ROUTING:
        return f"ad:{name}"
    return f"addata:{html.escape(name)}"


# Renders one attribute as an AttributeTypeAndValue or a replace Change node.
#
# `xsi:type="xsd:string"` is what a Windows client sends and what gives the
# envelope's already-declared xsi/xsd namespaces a purpose;
# `AttributeParser._read_values` reads the type to tell a string from base64.
def _node(name: str, values: Sequence[str], change: bool) -> str:
    rendered = "".join(
        f'<ad:value xsi:type="xsd:string">{html.escape(value)}</ad:value>'
        for value in values
    )
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
