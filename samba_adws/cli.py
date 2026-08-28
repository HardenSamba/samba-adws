"""The `samba-adws` command, which `MODULE.yaml` has promised since it was written.

**It exists so that another module can reach this one without importing it.**
The console in this ecosystem reaches every module through the command that
module installs, as a subprocess: a module owns its behaviour and its consumers
render it, and a consumer that imported this package would be holding another
module's code in its own process — with `python3-samba` underneath, which is
not thread-safe and is why the server forks rather than threads.

**One page per invocation.** See `cli_search`. The caller pages by asking again
with the cursor it was given.

**`naming-context` is where a consumer starts.** `search` requires a `--base`
and a console never knows a distinguished name until something published one.
See `cli_naming` for why it is a verb of its own rather than a field of
`status`. samba-adws#28.

**Read only, for now**, and the reason is checked rather than assumed.
`search` is the verb `hardensamba-webui#9` and `samba-adws#20` were blocked on.
The write verbs exist on `ADWSWriteClient` as of `samba-adws#16` and are
deliberately not exposed here, because the server still builds its request-time
session with `system_session()` — see the call in `classes/server/connection.py`
— so it acts as SYSTEM whoever asked. A `delete` verb on this command would
therefore let any ticket-holder who can reach port 9389 empty the directory.
That is `samba-adws#8`, and exposing a write verb is what it gates.

**`status` exists so that a consumer can ask whether this command answers.**
It opens nothing. `hardensamba-webui` probed with `search --help`, chosen
for the right reason - a probe must not need a base, a query or a
credential - and it could never work, because argparse prints help as text
and that console parses stdout as JSON. A module that was working
perfectly therefore read as installed and not answering. samba-adws#25.
"""

import argparse
from typing import Callable, Dict, List, Optional

from samba_adws import cli_format, cli_naming, cli_output, cli_search, cli_status
from samba_adws.client import ADWSClient
from samba_adws.errors import ADWSClientError
from samba_adws.search_client import ADWSSearchClient

DEFAULT_PORT = 9389


# Declares the arguments `search` takes.
def add_search(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--server", required=True, help="the controller to ask")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--base", required=True,
                        help="the container to read: a DN, <GUID=...>, or a bare objectGUID")
    parser.add_argument("--scope", default="OneLevel", choices=("Base", "OneLevel", "Subtree"))
    parser.add_argument("--filter", dest="ldap_filter", default="(objectClass=*)")
    parser.add_argument("--properties", default="", help="comma-separated, all when empty")
    parser.add_argument("--count", type=int, default=cli_search.DEFAULT_COUNT)
    parser.add_argument("--cursor", default="", help="opaque, from a previous answer")


# Builds the whole parser.
def parser() -> argparse.ArgumentParser:
    common = cli_format.shared()
    root = argparse.ArgumentParser(prog="samba-adws", parents=[common],
                                   description=__doc__.splitlines()[0])
    verbs = root.add_subparsers(dest="verb", required=True)
    top = verbs.add_parser("naming-context", help="the top of the domain, for --base",
                           parents=[common])
    cli_naming.add_arguments(top, DEFAULT_PORT)
    add_search(verbs.add_parser("search", help="one page of objects in a container",
                                parents=[common]))
    verbs.add_parser("status", help="whether this command answers", parents=[common])
    return root


# Reads the top of the domain and prints it, or the reason it could not.
def naming_context(options: argparse.Namespace) -> int:
    try:
        client = ADWSClient(options.server, options.port)
        return cli_output.emit(cli_naming.run(client), cli_format.wanted(options))
    except ADWSClientError as error:
        return cli_output.refuse(f"{error.code}: {error}")


# Runs one search and prints the page, or the reason it could not.
def search(options: argparse.Namespace) -> int:
    try:
        query = cli_search.query_from(
            options.base, options.scope, options.ldap_filter, options.properties
        )
        client = ADWSSearchClient(options.server, options.port)
        page = cli_search.run(client, query, options.cursor, options.count)
        return cli_output.emit(page, cli_format.wanted(options))
    except ADWSClientError as error:
        return cli_output.refuse(f"{error.code}: {error}")


# The entry point the package installs.
#
# The two verbs that open a connection are dispatched through a table rather
# than a third `if`, which is also what keeps this function inside the three
# return statements `.flake8` allows. `status` is not in it because it opens
# nothing and so takes no client.
def main(argv: Optional[List[str]] = None) -> int:
    options = parser().parse_args(argv)
    connected: Dict[str, Callable[[argparse.Namespace], int]] = {
        "naming-context": naming_context, "search": search,
    }
    if options.verb in connected:
        return connected[options.verb](options)
    if options.verb == "status":
        return cli_output.emit(cli_status.report(DEFAULT_PORT), cli_format.wanted(options))
    return cli_output.refuse(f"unknown verb: {options.verb}")
