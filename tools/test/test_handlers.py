#!/usr/bin/env python3
"""Isolated handler checks (no NMF/WCF/network). Run on the Samba DC."""
from __future__ import annotations

import logging
import os
import sys
from typing import Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

Result = Tuple[str, bool, str]
LOG = logging.getLogger("test_handlers")
GET_VERSION = (
    "http://schemas.microsoft.com/2008/1/ActiveDirectory"
    "/CustomActions/TopologyManagement/GetVersion"
)


def _envelope(action: str, message_id: str) -> str:
    return (
        '<s:Envelope '
        'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing">'
        f'<s:Header><a:Action>{action}</a:Action>'
        f'<a:MessageID>{message_id}</a:MessageID></s:Header>'
        '<s:Body/></s:Envelope>'
    )


def _registry():
    from samba.auth import system_session
    from classes.handlers.handler_registry import HandlerRegistry
    return HandlerRegistry(LOG, system_session())


def test_routing(reg) -> Result:
    from src.handlers.handler_routing import HANDLER_FACTORIES
    missing = [k for k, _ in HANDLER_FACTORIES if reg.resolve(k) is None]
    return ("routing resolves keys", not missing,
            "all resolve" if not missing else f"missing {missing}")


def test_get_version(reg) -> Result:
    from classes.parsing.context import RequestContext
    ctx = RequestContext.from_xml(_envelope(GET_VERSION, "urn:uuid:gv-1"))
    xml = reg.resolve(GET_VERSION).handle(ctx)
    ok = "<ca:Version" in xml and "urn:uuid:gv-1" in xml
    return ("GetVersion handle", ok, f"{len(xml)} bytes")


def test_relates_to(reg) -> Result:
    from classes.parsing.context import RequestContext
    ctx = RequestContext.from_xml(_envelope(GET_VERSION, "urn:uuid:rt-9"))
    xml = reg.resolve(GET_VERSION).handle(ctx)
    ok = "<a:RelatesTo>urn:uuid:rt-9</a:RelatesTo>" in xml
    return ("RelatesTo echoed", ok, "present" if ok else "MISSING")


def main() -> int:
    try:
        reg = _registry()
    except Exception as exc:
        print(f"[FAIL] cannot build registry (run on the DC): {exc}")
        return 1
    checks = [test_routing(reg), test_get_version(reg),
              test_relates_to(reg)]
    failures = 0
    for name, ok, detail in checks:
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        failures += 0 if ok else 1
    print(f"\n{len(checks) - failures}/{len(checks)} checks passed.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
