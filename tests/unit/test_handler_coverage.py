#!/usr/bin/env python3
"""Every registered handler is exercised by a test, and nothing else is."""
from __future__ import annotations

import ast
import os
from typing import List

from tests.dc.handler_actions import HANDLER_ACTIONS

ROUTING = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "src", "handlers", "handler_routing.py")


def registered_keys() -> List[str]:
    """Reads the registration keys from the source.

    Importing the routing module pulls in every handler and with them the
    directory bindings, which is exactly what this check must not require: a
    handler added without a test has to fail the suite on any machine.
    """
    tree = ast.parse(open(ROUTING, encoding="utf-8").read(), filename=ROUTING)
    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign) or not isinstance(node.target, ast.Name):
            continue
        if node.target.id != "HANDLER_FACTORIES" or node.value is None:
            continue
        return [pair.elts[0].value for pair in node.value.elts]  # type: ignore[attr-defined]
    raise AssertionError("HANDLER_FACTORIES not found in handler_routing.py")


def test_every_registered_handler_has_an_action_to_be_tested_with() -> None:
    """Adding a handler without adding it here fails the suite."""
    missing = sorted(set(registered_keys()) - set(HANDLER_ACTIONS))
    assert not missing, f"registered but never exercised: {missing}"


def test_no_action_is_declared_for_a_handler_that_is_gone() -> None:
    """Deleting a handler and leaving its test behind fails too."""
    stale = sorted(set(HANDLER_ACTIONS) - set(registered_keys()))
    assert not stale, f"exercised but not registered: {stale}"


def test_each_action_reaches_its_own_handler_by_the_routers_rule() -> None:
    """resolve() lowercases the exact table and does not lowercase the suffix."""
    for key, action in HANDLER_ACTIONS.items():
        assert action.rsplit("/", 1)[-1] == key or action.lower() != action, (
            f"{key}: {action} reaches neither the exact table nor the suffix rule")
