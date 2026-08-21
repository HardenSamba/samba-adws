"""Validation for the directory-changing client inputs."""

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


# Validates the non-empty new distinguished name for a rename.
def validate_new_dn(new_dn: str, target: str) -> None:
    if not isinstance(new_dn, str) or not new_dn.strip():
        raise ADWSClientError("New DN must be a non-empty distinguished name",
                              "InvalidArgument", target)


# Validates that a password is a non-empty string.
def validate_password(password: str, target: str) -> None:
    if not isinstance(password, str) or not password:
        raise ADWSClientError("Password must be a non-empty string",
                              "InvalidArgument", target)
