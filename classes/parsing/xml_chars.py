"""The characters XML 1.0 cannot carry, restored after parsing.

The server reads a request by turning its WCF binary records into XML text
and parsing that. Binary XML carries any code point; XML 1.0 refuses the C0
controls other than tab and line feed, and quietly rewrites carriage return
as line feed. src/wcf/records/text.py writes each of those as a private-use
marker followed by four hex digits so the text parses; this module is the
other half, and puts the characters back on every parsed tree so no handler
ever sees the marker. The one request that needs it in practice is
SetPassword: the ActiveDirectory module gives every computer it creates a
random 120-character password drawn from the whole of Unicode.
"""

import re
import xml.etree.ElementTree as ET
from typing import Optional

from src.wcf.records.text import XML_CHAR_MARKER

_MARKER: str = XML_CHAR_MARKER
_MARKED = re.compile(re.escape(_MARKER) + r"([0-9A-F]{4})")


# The text as the client sent it: every marker becomes the character it
# stands for. Text without a marker is returned as is, None included.
def restore(text: Optional[str]) -> Optional[str]:
    if not text or _MARKER not in text:
        return text
    return _MARKED.sub(lambda match: chr(int(match.group(1), 16)), text)


# Restores every text, tail and attribute value under root, in place, and
# returns root so a parse can be wrapped in one call.
def restore_tree(root: ET.Element) -> ET.Element:
    for element in root.iter():
        element.text = restore(element.text)
        element.tail = restore(element.tail)
        for key, value in element.attrib.items():
            element.attrib[key] = restore(value) or ""
    return root
