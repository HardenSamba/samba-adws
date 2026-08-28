"""The `naming-context` subcommand: where the top of the domain is.

**`search` requires a `--base`, and nothing published one.** A console never
knows a distinguished name until it has listed something, and it cannot list
anything until it knows which container to list — so the first question a
consumer has to ask is where the tree starts. The server has answered it since
the RootDSE branch of `GetHandler` was written; no verb named it, so
`hardensamba-webui` had no way in.

**Its own verb rather than a field of `status`.** `status` promises a probe
that opens nothing: no base, no query, no credential, no socket. Reading a
naming context opens one, against a named controller, and fails for every
reason a directory read fails for. Folding it in would make the one call that
must always answer depend on a domain being reachable.

**The key is the directory's own.** `defaultNamingContext` is what the RootDSE
calls it and it leaves unchanged, as the attributes of `search` do: a consumer
wanting a friendlier `base` would be asking this command to hold its
vocabulary, and there is more than one consumer.
"""

import argparse
from typing import Any, Dict

from samba_adws._root_dse import DEFAULT_NAMING_CONTEXT
from samba_adws.client import ADWSClient


# Declares the arguments `naming-context` takes.
#
# The port default is passed in because `cli` owns it, and importing `cli`
# from a module `cli` imports would be circular.
def add_arguments(parser: argparse.ArgumentParser, default_port: int) -> None:
    parser.add_argument("--server", required=True, help="the controller to ask")
    parser.add_argument("--port", type=int, default=default_port)


# The top of the domain, in the shape this command promises.
def run(client: ADWSClient) -> Dict[str, Any]:
    return {DEFAULT_NAMING_CONTEXT: client.naming_context()}
