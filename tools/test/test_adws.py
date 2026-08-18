#!/usr/bin/env python3
"""Environment diagnostic for SambaAD ADWS (run first, on the DC)."""
from __future__ import annotations

import logging
import os
import socket
import sys
from typing import Callable, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

Result = Tuple[str, bool, str]


def check_port() -> Result:
    try:
        with socket.create_connection(("127.0.0.1", 9389), timeout=2):
            return ("port 9389 open", True, "listening")
    except OSError as exc:
        return ("port 9389 open", False, str(exc))


def check_imports() -> Result:
    missing: List[str] = []
    for name in ["samba", "samba.samdb", "ldb", "gssapi"]:
        try:
            __import__(name)
        except Exception as exc:
            missing.append(f"{name} ({exc})")
    if missing:
        return ("core imports", False, "; ".join(missing))
    return ("core imports", True, "samba/ldb/gssapi OK")


def check_samdb() -> Result:
    try:
        from classes.directory import SambaDB
        db = SambaDB(logging.getLogger("diag"))
        nc = db.naming_context()
        return ("SamDB connect", bool(nc), f"defaultNC={nc!r}")
    except Exception as exc:
        return ("SamDB connect", False, str(exc))


def check_wcf() -> Result:
    try:
        from src.wcf.records import dump_records  # noqa: F401
        from src.wcf.xml2records import XMLParser
        records = XMLParser.parse("<a>b</a>")
        return ("WCF/XML parse", records is not None,
                f"type={type(records).__name__}")
    except Exception as exc:
        return ("WCF/XML parse", False, str(exc))


# Guards the WCF decode "undefined entity" accent bug: the text escaper
# (wcf/records/text.py, called by print_records on every decoded request) must
# escape only XML-significant chars and leave non-ASCII literal so ET parses it.
def check_wcf_unicode() -> Result:
    import xml.etree.ElementTree as ET
    from src.wcf.records.text import escape
    value = "créé < & \" société"
    try:
        root = ET.fromstring(f"<r>{escape(value)}</r>")
        ok = root.text == value
        return ("WCF non-ASCII escape", ok, f"text={root.text!r}")
    except Exception as exc:
        return ("WCF non-ASCII escape", False, str(exc))


def check_routing() -> Result:
    try:
        from src.handlers.handler_routing import (
            ACTION_HANDLER_KEYS, HANDLER_FACTORIES)
        ok = bool(HANDLER_FACTORIES) and bool(ACTION_HANDLER_KEYS)
        return ("handler routing", ok,
                f"{len(HANDLER_FACTORIES)} handlers, "
                f"{len(ACTION_HANDLER_KEYS)} actions")
    except Exception as exc:
        return ("handler routing", False, str(exc))


def _run(checks: List[Callable[[], Result]]) -> int:
    failures = 0
    for check in checks:
        name, ok, detail = check()
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        failures += 0 if ok else 1
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed.")
    return 1 if failures else 0


def main() -> int:
    return _run([
        check_port, check_imports, check_samdb,
        check_wcf, check_wcf_unicode, check_routing,
    ])


if __name__ == "__main__":
    raise SystemExit(main())
