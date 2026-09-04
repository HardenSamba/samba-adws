"""The typed result of making an account usable.

A record rather than a mapping, because a caller reads three things off it and
each has a type: where the object is, what the directory named it, and how far
the sequence got. `reached` is one of the three step names `accounts` exports.
"""

from typing import NamedTuple


# One account as the sequence left it: its name, its identifier, and the last
# of the three exchanges that succeeded.
class Account(NamedTuple):
    dn: str
    guid: str
    reached: str
