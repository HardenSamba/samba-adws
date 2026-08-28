"""The three spellings a search base may arrive in, and the two it leaves in.

**A console holds GUIDs, not distinguished names.** A DN is a position in the
tree and it changes the moment somebody renames an organisational unit or drags
an account into another one; an `objectGUID` is issued once and never changes.
A consumer that stored `OU=Staff,OU=Paris,DC=example,DC=test` for a saved view
finds it broken after a reorganisation, which is why `hardensamba-webui` keeps
the GUID and needs to be able to hand one back as a base.

**The wire form is LDAP's own extended DN, `<GUID=...>`.** It is not invented
here: it is the syntax `ldb` and Active Directory both spell an object identity
in, and it travels through `<adlq:BaseObject>` as ordinary text. A bare GUID is
accepted as a convenience and normalised into that form, because a bare GUID
contains no `=` and can therefore never have been a distinguished name — there
is nothing to guess between. Anything else leaves as it arrived, trimmed: this
module recognises a GUID, it does not judge a DN. Active Directory's three-part
extended DN, `<GUID=...>;<SID=...>;DN`, is one of those: it already carries a
distinguished name, so it is passed on rather than rewritten.

**A malformed GUID is refused here.** Once a caller has written `<GUID=`, it
has said what it means, and answering a typo with a `Search failed` fault that
travelled to a domain controller first tells the caller much less than a
message naming the value that is not a GUID. A truncated paste is not quietly
completed either: `{` without its closing brace is not the shape a directory
prints, so it is not read as a GUID at all.

**`is_guid_base` answers exactly what `normalize_base` will do.** Both decide
through `_guid_of`, shape *and* `uuid` parse together, so the predicate cannot
promise a GUID the normaliser then refuses: a consumer that branches on it will
not be handed the `ADWSClientError` its chosen branch had just ruled out.
"""

import re
import uuid
from typing import Optional

from samba_adws.errors import ADWSClientError

# How a GUID base is spelled on the wire once this module is done with it.
EXTENDED_FORM = "<GUID={0}>"

# The explicit spelling. Case-insensitive, because LDAP treats it that way and
# a caller that typed `<guid=...>` meant the same thing.
_EXTENDED = re.compile(r"^<\s*guid\s*=\s*(?P<guid>[^>]*)>$", re.IGNORECASE)

# The only shape a directory ever prints a GUID in: 8-4-4-4-12 hex.
_HEX = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

# A bare GUID, optionally in the braces PowerShell wraps it in. The braces are
# one alternative rather than two independent `?`, so a half-copied `{...` does
# not match: it is a truncated paste, and repairing it would invent a value.
_BARE = re.compile(rf"^(?:{_HEX}|\{{{_HEX}\}})$", re.IGNORECASE)


# Whether a base names its object by objectGUID rather than by position.
#
# True exactly when `normalize_base` rewrites the base into `EXTENDED_FORM`,
# which is what makes the answer safe to branch on.
def is_guid_base(base: str) -> bool:
    return _guid_of(base.strip()) is not None


# Returns the extended-DN form of a GUID base, or any other base trimmed.
#
# Trimming is not cosmetic: this function decides what `SearchQuery.base` holds
# and therefore what goes on the wire, so a pasted DN and a pasted GUID have to
# lose their surrounding spaces alike rather than one of the two carrying them.
def normalize_base(base: str) -> str:
    stripped = base.strip()
    canonical = _guid_of(stripped)
    if canonical is not None:
        return EXTENDED_FORM.format(canonical)
    explicit = _EXTENDED.match(stripped)
    if explicit is not None:
        raise _not_a_guid(base, explicit.group("guid").strip())
    return stripped


# The canonical text of the GUID a base spells, or None if it spells none.
#
# A bare match is hex by construction, so `uuid` cannot refuse one; the explicit
# form carries whatever the caller typed between `<GUID=` and `>`, so it is
# parsed and not merely matched. That parse is the one `is_guid_base` shares.
def _guid_of(stripped: str) -> Optional[str]:
    explicit = _EXTENDED.match(stripped)
    if explicit is None:
        return str(uuid.UUID(stripped)) if _BARE.match(stripped) else None
    try:
        return str(uuid.UUID(explicit.group("guid").strip()))
    except ValueError:
        return None


# The refusal a base earns by opening `<GUID=` and carrying no GUID.
#
# The message and `target` quote the base as the caller typed it, so it can be
# found in the caller's own source, and the payload separately, so the caller
# is told which part of it is the problem.
def _not_a_guid(base: str, candidate: str) -> ADWSClientError:
    message = (
        f"Search base {base!r} uses the <GUID=...> form but {candidate!r} "
        "is not an objectGUID"
    )
    return ADWSClientError(message, "InvalidArgument", base)
