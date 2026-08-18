from typing import Any


def filter_for_offered(name: str, fmt_offered: str) -> str:
    kind = (fmt_offered or "").lower()
    if "1779" in kind or "distinguished" in kind:
        return f"(distinguishedName={name})"
    if "nt4" in kind or "ntaccount" in kind:
        short = name.split("\\")[-1]
        return f"(sAMAccountName={short})"
    if "userprincipal" in kind or "upn" in kind:
        return f"(userPrincipalName={name})"
    if "spn" in kind or "service" in kind:
        return f"(servicePrincipalName={name})"
    if "guid" in kind or "uniqueid" in kind:
        stripped = name.strip("{}")
        return f"(objectGUID={stripped})"
    if "sid" in kind:
        return f"(objectSid={name})"
    return (
        f"(|(sAMAccountName={name})(userPrincipalName={name})"
        f"(distinguishedName={name})(cn={name}))"
    )


def first_text(entry: Any, attr: str) -> str:
    if attr not in entry:
        return ""
    raw = entry[attr][0]
    return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
