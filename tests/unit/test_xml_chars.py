#!/usr/bin/env python3
"""The characters XML 1.0 cannot carry survive the request path.

New-ADComputer, and so the Administrative Center's New Computer dialog, sets
a random 120-character password on the object it just created, drawn from
the whole of Unicode: C0 controls, carriage returns, the lot. WCF binary
XML carries them; the XML text the server parses could not, so SetPassword
faulted with "not well-formed (invalid token)" and every computer created
from Windows stayed disabled with no password. These tests pin the two
halves of the fix and the whole path between them.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from io import BytesIO, StringIO
from typing import Any

import pytest
from src.wcf.records import Record, dump_records, print_records
from src.wcf.records.text import XML_CHAR_MARKER, escape
from src.wcf.xml2records import XMLParser

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.parsing.xml_chars import restore, restore_tree

# A password the ActiveDirectory module could generate: every kind of code
# point XML refuses, around ones it accepts.
AWKWARD = "\x01A\x1f\r\nb\tc\x0b\x0cde\x7fé\U0001f600￾\x00"

ENVELOPE = (
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"'
    ' xmlns:a="http://www.w3.org/2005/08/addressing">'
    "<s:Header><a:Action s:mustUnderstand=\"1\">http://schemas.microsoft.com/2008/1/"
    "ActiveDirectory/CustomActions/AccountManagement/SetPassword</a:Action>"
    "<a:MessageID>urn:uuid:18610b53-7b21-416f-90f8-fd1533cc8a50</a:MessageID>"
    "</s:Header><s:Body>"
    '<SetPasswordRequest xmlns="http://schemas.microsoft.com/2008/1/ActiveDirectory/'
    'CustomActions"><AccountDN>CN=PC1,CN=Computers,DC=samba,DC=local</AccountDN>'
    "<NewPassword>{}</NewPassword><PartitionDN>DC=samba,DC=local</PartitionDN>"
    "</SetPasswordRequest></s:Body></s:Envelope>"
)


def test_the_escaper_writes_no_character_xml_refuses() -> None:
    text = escape(AWKWARD)
    assert "\x01" not in text and "\r" not in text and "\x00" not in text
    ET.fromstring(f"<v>{text}</v>")


def test_the_marker_and_the_hex_are_what_the_escaper_writes() -> None:
    assert escape("\x01") == XML_CHAR_MARKER + "0001"
    assert escape("\r") == XML_CHAR_MARKER + "000D"
    assert escape(XML_CHAR_MARKER) == XML_CHAR_MARKER + "E000"


def test_tab_line_feed_and_ordinary_text_are_left_alone() -> None:
    assert escape("a\tb\nc é") == "a\tb\nc é"


@pytest.mark.parametrize("value", [AWKWARD, "\r", "\r\n", XML_CHAR_MARKER, "plain", ""])
def test_restore_undoes_escape_exactly(value: str) -> None:
    assert restore(escape(value)) == value


def test_restore_leaves_none_and_marker_free_text_untouched() -> None:
    assert restore(None) is None
    assert restore("no marker here") == "no marker here"


def test_restore_tree_reaches_text_tail_and_attributes() -> None:
    root = ET.fromstring(f"<r a='{escape(chr(1))}'><c>{escape(chr(2))}</c>{escape(chr(3))}</r>")
    restore_tree(root)
    child = root[0]
    assert root.attrib["a"] == "\x01" and child.text == "\x02" and child.tail == "\x03"


# The records XMLParser builds from an envelope carrying a placeholder, with
# the placeholder's text record holding the value XML itself could not.
def records_with_value(value: str) -> Any:
    records = XMLParser.parse(ENVELOPE.format("PLACEHOLDER"))
    replace_placeholder(records, value)
    return records


def replace_placeholder(records: Any, value: str) -> None:
    for record in records:
        if getattr(record, "value", None) == "PLACEHOLDER":
            record.value = value
        replace_placeholder(getattr(record, "childs", []), value)


def test_a_password_the_client_sent_in_binary_reaches_the_handler_intact() -> None:
    """The whole server path: bytes, records, text, parsed context, body."""
    wire = dump_records(records_with_value(AWKWARD))
    out = StringIO()
    print_records(Record.parse(BytesIO(wire)), fp=out)
    text = out.getvalue()
    context = RequestContext.from_xml(text)
    assert context.action.endswith("/AccountManagement/SetPassword")
    parser = BodyParser(context.raw_xml or "")
    body = parser.find_custom_body("SetPasswordRequest")
    assert parser.text_of(body, "NewPassword") == AWKWARD
    assert parser.text_of(body, "AccountDN") == "CN=PC1,CN=Computers,DC=samba,DC=local"


def test_a_carriage_return_is_not_turned_into_a_line_feed() -> None:
    """XML parsers normalise CR to LF; a password is not a line ending."""
    context = RequestContext.from_xml(ENVELOPE.format(escape("a\rb")))
    body = BodyParser(context.raw_xml or "").find_custom_body("SetPasswordRequest")
    assert BodyParser(context.raw_xml or "").text_of(body, "NewPassword") == "a\rb"
