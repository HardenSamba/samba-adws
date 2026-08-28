"""The RootDSE: the one object a caller may ask for before it knows anything."""

from typing import Mapping

from samba_adws.errors import ADWSClientError

# The object reference the server routes to its RootDSE branch. `GetHandler`
# treats an empty reference, "root dse" and this GUID alike, and the GUID is
# what a Windows client sends: `documentation/04-handlers.md` records it.
ROOT_DSE_IDENTITY = "11111111-1111-1111-1111-111111111111"

# The distinguished name at the top of the domain, under the name the directory
# gives it. The server's own accessor asks the RootDSE for the same attribute.
DEFAULT_NAMING_CONTEXT = "defaultNamingContext"


# Every refusal from this module, under the one code and target it can have.
def _refused(reason: str) -> ADWSClientError:
    return ADWSClientError(reason, "MalformedResponse", ROOT_DSE_IDENTITY)


# One naming context out of a RootDSE answer, or the reason there is none.
#
# The lookup ignores case because the answer carries the directory's spelling
# rather than ours: the server matches a projection against its own `*` search
# case-insensitively and returns the keys LDB gave it.
#
# `kind` must name an attribute holding a single distinguished name. The
# multi-valued `namingContexts` decodes to a tuple, and this refuses it rather
# than returning whichever value came first - a caller that asked for every
# context would receive one of them with no way to tell which or how many were
# dropped. The two refusals are worded apart because "published none" sent for
# an attribute the server did publish points the reader at the wrong machine.
def naming_context_of(attributes: Mapping[str, object], kind: str) -> str:
    wanted = kind.lower()
    published = [held for name, held in attributes.items() if name.lower() == wanted]
    if not published:
        raise _refused(f"The server published no {kind}")
    held = published[0]
    if not isinstance(held, str) or not held.strip():
        raise _refused(f"The server published {kind}, but not as one naming context")
    return held
