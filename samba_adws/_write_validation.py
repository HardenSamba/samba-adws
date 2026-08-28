"""Validation for the directory-changing client inputs.

**An empty sequence means different things on the two verbs.** On a create it is
a mistake — an attribute named with nothing to put in it — and is refused. On a
modify it is the way to clear an attribute, and is sent. `allow_empty` is that
distinction and nothing else.

**A string is not a sequence of strings.** `{"cn": "Ann"}` would otherwise reach
the wire as three single-character values, which is the kind of thing an
administrator finds in the directory a week later.
"""

from typing import Dict, Mapping, Sequence, Tuple

from samba_adws.errors import ADWSClientError


# Validates one attribute's name and its sequence of string values.
def _clean_values(name: str, values: Sequence[str], allow_empty: bool,
                  target: str) -> Tuple[str, ...]:
    if not isinstance(name, str) or not name.strip():
        raise ADWSClientError("Attribute names must be non-empty strings",
                              "InvalidArgument", target)
    if isinstance(values, (str, bytes)):
        raise ADWSClientError(f"Values for {name} must be a sequence",
                              "InvalidArgument", target)
    cleaned = tuple(values)
    if any(not isinstance(v, str) for v in cleaned):
        raise ADWSClientError(f"Values for {name} must be strings",
                              "InvalidArgument", target)
    if not cleaned and not allow_empty:
        raise ADWSClientError(f"{name} needs at least one value",
                              "InvalidArgument", target)
    return cleaned


# Validates a name-to-values mapping into an immutable, string-checked form.
def validate_named_values(mapping: Mapping[str, Sequence[str]], allow_empty: bool,
                          target: str) -> Dict[str, Tuple[str, ...]]:
    if not isinstance(mapping, Mapping):
        raise ADWSClientError("Attributes must be a mapping", "InvalidArgument", target)
    result: Dict[str, Tuple[str, ...]] = {}
    for name, values in mapping.items():
        result[name] = _clean_values(name, values, allow_empty, target)
    return result


# Validates that a rename changes the name, the parent, or both.
#
# Neither is not a no-op worth sending: `ModifyHandler._apply_rename` would find
# no rename keys, skip the rename entirely and answer success, so a caller that
# meant to move something would be told it had.
#
# **A half that is present but blank is refused on its own.** Absence is what
# `build_rename_request` reads to mean "keep what the object has", and it reads
# it as plain truthiness, so `new_rdn="   "` is a half that is *given* — it goes
# out as a relative name of three spaces and comes back as a server-side
# ModifyFailed. Checking only whether both halves are blank together would let
# that through whenever the other half was real, which is the mixed case.
def validate_rename(new_rdn: str, new_parent: str, target: str) -> None:
    for value in (new_rdn, new_parent):
        if not isinstance(value, str):
            raise ADWSClientError("A new name and a new parent must be strings",
                                  "InvalidArgument", target)
        if value and not value.strip():
            raise ADWSClientError("A new name and a new parent cannot be blank",
                                  "InvalidArgument", target)
    if not new_rdn and not new_parent:
        raise ADWSClientError("A rename needs a new name, a new parent, or both",
                              "InvalidArgument", target)


# Validates that a password is a non-empty string.
def validate_password(password: str, target: str) -> None:
    if not isinstance(password, str) or not password:
        raise ADWSClientError("Password must be a non-empty string",
                              "InvalidArgument", target)
