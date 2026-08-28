"""How the command answers: JSON on stdout, a reason on stderr, an exit status.

The consumer is another module running this as a subprocess, not a person
reading a terminal. `hardensamba-webui` starts it, waits with a deadline, and
then does exactly two things: check the exit status, and parse stdout as JSON.
Anything else on stdout makes a working answer unreadable, and a zero status
with a broken payload is the failure that is hardest to trace, because the
consumer reports a parse error and the module reports success.

So: one JSON document on stdout and nothing else, or a non-zero status with the
reason on stderr and stdout left empty.
"""

import json
import sys
from typing import Any, Mapping

from samba_adws import cli_text

# What a consumer sees when the command worked and when it did not.
OK = 0
FAILED = 1


# Writes one JSON document to stdout and returns the success status.
def answer(payload: Mapping[str, Any]) -> int:
    json.dump(payload, sys.stdout, ensure_ascii=False, separators=(",", ":"))
    sys.stdout.write("\n")
    return OK


# The same answer in whichever form the caller asked for.
#
# json is the default, and that is this module's decision rather than the
# ecosystem's: the consumer is another module running this as a subprocess, and
# the one verb that existed before this flag has always printed JSON. A text
# default would have changed what every caller written before it receives.
def emit(payload: Mapping[str, Any], wanted: str) -> int:
    if wanted == "text":
        sys.stdout.write(cli_text.render(payload) + "\n")
        return OK
    return answer(payload)


# Writes one reason to stderr, leaving stdout empty, and returns the failure.
#
# Empty rather than an error document: a consumer that parsed stdout on a
# non-zero status would be reading a shape this command does not promise, and
# one that did not would find half a page.
def refuse(reason: str) -> int:
    sys.stderr.write(f"{reason}\n")
    return FAILED
