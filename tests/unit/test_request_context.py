#!/usr/bin/env python3
"""RequestContext: what the server believes a request said."""
from __future__ import annotations

from typing import Any

import pytest
from classes.parsing.context import RequestContext

GET = "http://schemas.xmlsoap.org/ws/2004/09/transfer/Get"


def test_the_action_and_message_id_are_read(envelope: Any) -> None:
    context = RequestContext.from_xml(envelope(GET, "urn:uuid:ctx-1"))
    assert context.action == GET
    assert context.message_id == "urn:uuid:ctx-1"


def test_an_awkward_message_id_survives_parsing(envelope: Any, awkward: str) -> None:
    """It is echoed straight back into a header, so it must arrive intact."""
    escaped = awkward.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    context = RequestContext.from_xml(envelope(GET, escaped))
    assert context.message_id == awkward


def test_a_missing_message_id_is_empty_rather_than_none(envelope: Any) -> None:
    """WS-Addressing permits the omission; the field must stay a string."""
    xml = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing">'
        f'<s:Header><a:Action>{GET}</a:Action></s:Header>'
        '<s:Body/></s:Envelope>'
    )
    assert RequestContext.from_xml(xml).message_id == ""


def test_a_missing_action_reads_as_unknown(envelope: Any) -> None:
    xml = (
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
        'xmlns:a="http://www.w3.org/2005/08/addressing">'
        '<s:Header><a:MessageID>urn:uuid:ctx-2</a:MessageID></s:Header>'
        '<s:Body/></s:Envelope>'
    )
    assert RequestContext.from_xml(xml).action == "Unknown"


def test_unparseable_xml_raises_value_error() -> None:
    """The dispatcher relies on this, not on a bare ParseError."""
    with pytest.raises(ValueError):
        RequestContext.from_xml("<s:Envelope><Broken")


def test_the_raw_request_is_kept_for_handlers_that_reparse(envelope: Any) -> None:
    request = envelope(GET, "urn:uuid:ctx-3")
    assert RequestContext.from_xml(request).raw_xml == request
