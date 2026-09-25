"""What this module reports about itself, without opening anything."""

from typing import Any, Dict

from samba_adws import __version__

# The verbs this command installs. Named rather than derived from the parser,
# because a consumer reads this to decide what it may call and a list built
# from the parser would grow a verb the moment somebody added a flag.
VERBS = ("naming-context", "search", "status", "new-user", "set-password")


# What this command is and what it would talk to, without talking to anything.
#
# A probe asks one narrow question: does this command exist and can it answer.
# It must not need a base the caller does not know yet, must not run a query
# against a domain to answer "are you there", and must not depend on a
# credential. So nothing here opens a socket. Whether this module can read a
# directory is established by reading one, and the screen that does says so
# when it cannot.
#
# It answers at all only because importing this module succeeded, which is the
# part a consumer actually needs to know: the package is installed and its
# client is importable in the interpreter the command runs under.
def report(port: int) -> Dict[str, Any]:
    return {"module": "samba-adws", "version": __version__,
            "verbs": list(VERBS), "default_port": port}
