"""The SYSTEM directory session, for the local paths allowed to hold one."""

from typing import Any


# The directory session local maintenance runs as, and no remote request does.
#
# `SambaDB` used to fall back to this whenever it was handed nothing, so a
# request that arrived carrying no identity opened the directory with every
# right in it and looked exactly like one that had them. #8 removed the
# fallback; this names what is left, so a caller that wants SYSTEM has to ask
# for it by name and the ADWS request path has no way to ask for it by accident.
def local_session() -> Any:
    from samba.auth import system_session

    return system_session()
