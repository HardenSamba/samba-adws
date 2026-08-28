#!/usr/bin/env python3
"""Shared fixtures, and the rule that keeps the suite runnable off a DC."""
from __future__ import annotations

import importlib
import logging
import os
import sys
from typing import Any, Iterator

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# The one string every write path is fed: an accent that must not be escaped
# into an entity ElementTree cannot resolve, and the five characters XML does
# define entities for.
AWKWARD = "créé & <société> \"x\" 'y'"


def _has_samba() -> bool:
    try:
        importlib.import_module("samba")
        importlib.import_module("ldb")
    except ImportError:
        return False
    return True


HAS_SAMBA = _has_samba()


def pytest_collection_modifyitems(config: pytest.Config,
                                  items: list[pytest.Item]) -> None:
    """Skips the directory-dependent tests rather than letting them error."""
    if HAS_SAMBA:
        return
    skip = pytest.mark.skip(reason="needs a provisioned Samba AD DC (python3-samba absent)")
    for item in items:
        if "dc" in item.keywords:
            item.add_marker(skip)


@pytest.fixture
def awkward() -> str:
    """The non-ASCII and XML-significant string used on every write path."""
    return AWKWARD


@pytest.fixture
def logger() -> logging.Logger:
    """A logger that swallows its output, so a failing test reads cleanly."""
    log = logging.getLogger("tests")
    log.addHandler(logging.NullHandler())
    return log


@pytest.fixture
def envelope() -> Any:
    """Builds a minimal SOAP request carrying an action and a MessageID."""
    def build(action: str, message_id: str, body: str = "") -> str:
        return (
            '<s:Envelope '
            'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing">'
            f'<s:Header><a:Action>{action}</a:Action>'
            f'<a:MessageID>{message_id}</a:MessageID></s:Header>'
            f'<s:Body>{body}</s:Body></s:Envelope>'
        )
    return build


@pytest.fixture
def registry(logger: logging.Logger) -> Iterator[Any]:
    """A handler registry built per test, never at module level (CLAUDE.md 5).

    Deliberately SYSTEM, and asked for by name. These tests drive handlers
    below the network, where there is no negotiation to take an identity from,
    so they prove the wiring and never the authorization. What proves the
    authorization is `tests/dc/test_session_security.py`, which asks a real
    directory.
    """
    from classes.directory.maintenance import local_session
    from classes.handlers.handler_registry import HandlerRegistry
    yield HandlerRegistry(logger, local_session())
