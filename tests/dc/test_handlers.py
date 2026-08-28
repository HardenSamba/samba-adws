#!/usr/bin/env python3
"""Handlers in isolation, against a real directory. Skipped without one."""
from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

import pytest

from tests.dc.handler_actions import HANDLER_ACTIONS

pytestmark = pytest.mark.dc

WSA = "{http://www.w3.org/2005/08/addressing}"
GET_VERSION = HANDLER_ACTIONS["GetVersion"]


# Drives one handler end to end below the network and returns its XML.
def answered(registry: Any, envelope: Any, action: str, message_id: str) -> str:
    from classes.parsing.context import RequestContext

    handler = registry.resolve(action)
    assert handler is not None, f"no handler resolves {action}"
    return str(handler.handle(RequestContext.from_xml(envelope(action, message_id))))


# Migrated from tools/test/test_handlers.py, now failing the suite.
def test_every_registered_key_resolves(registry: Any) -> None:
    unresolved = [key for key in HANDLER_ACTIONS if registry.resolve(key) is None]
    assert not unresolved


# Whatever it answers, including a fault, it parses and relates back. That is
# the CLAUDE.md section 5 invariant, and it is the one assertion that holds for
# every registered key without guessing at each body's shape.
@pytest.mark.parametrize("key", sorted(HANDLER_ACTIONS))
def test_a_handler_answers_and_relates_to_its_request(
        key: str, registry: Any, envelope: Any) -> None:
    answer = answered(registry, envelope, HANDLER_ACTIONS[key], f"urn:uuid:{key}-1")
    relates = ET.fromstring(answer).find(f".//{WSA}RelatesTo")
    assert relates is not None, f"{key} answered without a RelatesTo"
    assert relates.text == f"urn:uuid:{key}-1"


# Migrated from tools/test/test_handlers.py.
def test_get_version_answers_with_a_version(registry: Any, envelope: Any) -> None:
    answer = answered(registry, envelope, GET_VERSION, "urn:uuid:gv-1")
    assert ET.fromstring(answer).find(".//{*}Version") is not None


# The identifier is a client's to choose and goes straight into a header.
def test_an_awkward_message_id_is_echoed_intact(
        registry: Any, envelope: Any, awkward: str) -> None:
    escaped = awkward.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    answer = answered(registry, envelope, GET_VERSION, escaped)
    relates = ET.fromstring(answer).find(f".//{WSA}RelatesTo")
    assert relates is not None
    assert relates.text == awkward
