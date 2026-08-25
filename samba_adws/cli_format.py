"""The `--format` flag: what a caller wants back, and where it may say so."""

import argparse

# What a caller wants back. json is first because it is the default, and it is
# the default because the consumer is another module running this as a
# subprocess: the one verb that existed before this flag has always printed
# JSON, and a text default would change what every caller written before it
# receives.
FORMATS = ("json", "text")


# The flag every verb inherits, with no default of its own.
#
# SUPPRESS rather than a value, so that --format works on either side of the
# verb. argparse gives a subparser's default priority over whatever the root
# already parsed, so a real default here would silently produce json for
# `samba-adws --format text status` — and the position a person writes first is
# the one that would break.
def shared() -> argparse.ArgumentParser:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", choices=FORMATS, default=argparse.SUPPRESS,
                        help="json for a program, text for a person")
    return common


# Which form the caller asked for, or the default when it asked for none.
def wanted(options: argparse.Namespace) -> str:
    return str(getattr(options, "format", FORMATS[0]))
