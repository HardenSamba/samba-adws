import re
from typing import Dict, Optional

_IDENTIFIER_PATTERN = re.compile(
    r"<(?:wse:)?Identifier[^>]*>([^<]+)</(?:wse:)?Identifier>",
    re.IGNORECASE,
)

_EXPIRES_PATTERN = re.compile(
    r"<(?:wse:)?Expires[^>]*>([^<]+)</(?:wse:)?Expires>",
    re.IGNORECASE,
)

_DATE_UNITS: Dict[str, int] = {"Y": 365 * 86400, "M": 30 * 86400, "D": 86400}
_TIME_UNITS: Dict[str, int] = {"H": 3600, "M": 60, "S": 1}


def extract_identifier(raw_xml: Optional[str]) -> Optional[str]:
    if not raw_xml:
        return None
    match = _IDENTIFIER_PATTERN.search(raw_xml)
    if not match:
        return None
    raw = match.group(1).strip()
    if raw.lower().startswith("uuid:"):
        return raw[5:]
    return raw


def parse_expires(raw_xml: Optional[str]) -> int:
    if not raw_xml:
        return 3600
    match = _EXPIRES_PATTERN.search(raw_xml)
    if not match:
        return 3600
    return _duration_to_seconds(match.group(1).strip())


def _duration_to_seconds(text: str) -> int:
    if not text or text[0] != "P":
        return 3600
    body = text[1:]
    if "T" in body:
        date_part, time_part = body.split("T", 1)
    else:
        date_part, time_part = body, ""
    seconds = _sum_part(date_part, _DATE_UNITS) + _sum_part(time_part, _TIME_UNITS)
    return seconds or 3600


def _sum_part(text: str, units: Dict[str, int]) -> int:
    total = 0
    for num, unit in re.findall(r"(\d+)([A-Z])", text):
        total += int(num) * units.get(unit, 0)
    return total
