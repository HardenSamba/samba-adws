"""Regression tests for SOAP request-context extraction."""

import pytest

from classes.parsing.context import RequestContext

SOAP_PREFIX = """
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://www.w3.org/2005/08/addressing"
 xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory"
 xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration"
 xmlns:adlq="http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/LdapQuery">
"""


# Verifies all LDAP query fields and attribute QName normalization.
def test_enumerate_fields_keep_their_legacy_values() -> None:
    xml = SOAP_PREFIX + """
      <s:Header><a:Action>Enumerate</a:Action><a:MessageID>message-1</a:MessageID></s:Header>
      <s:Body><wsen:Enumerate><adlq:LdapQuery>
        <adlq:BaseObject>DC=example,DC=test</adlq:BaseObject>
        <adlq:Filter>(&amp;(objectClass=user))</adlq:Filter>
        <adlq:Scope>Subtree</adlq:Scope>
        <ad:SelectionProperty>ad:name</ad:SelectionProperty>
        <ad:SelectionProperty>addata:displayName</ad:SelectionProperty>
      </adlq:LdapQuery></wsen:Enumerate></s:Body></s:Envelope>
    """
    context = RequestContext.from_xml(xml)
    assert (context.action, context.message_id) == ("Enumerate", "message-1")
    assert context.base_dn == "DC=example,DC=test"
    assert context.ldap_filter == "(&(objectClass=user))"
    assert context.ldap_scope == "Subtree"
    assert context.selection_attributes == ["name", "displayName"]


# Verifies Release precedence without discarding the Pull batch size.
def test_release_context_overrides_pull_but_keeps_pull_maximum() -> None:
    xml = SOAP_PREFIX + """
      <s:Body>
        <wsen:Pull><wsen:EnumerationContext>pull-id</wsen:EnumerationContext>
          <wsen:MaxElements>25</wsen:MaxElements></wsen:Pull>
        <wsen:Release><wsen:EnumerationContext>release-id</wsen:EnumerationContext></wsen:Release>
      </s:Body></s:Envelope>
    """
    context = RequestContext.from_xml(xml)
    assert context.enumeration_context == "release-id"
    assert context.max_elements == 25


# Verifies unqualified addressing fallbacks and invalid batch sizes.
def test_unnamespaced_headers_and_invalid_maximum_keep_fallbacks() -> None:
    xml = SOAP_PREFIX + """
      <s:Header><Action>Fallback</Action><MessageID>plain-id</MessageID></s:Header>
      <s:Body><wsen:Pull><wsen:EnumerationContext>pull-id</wsen:EnumerationContext>
        <wsen:MaxElements>invalid</wsen:MaxElements></wsen:Pull></s:Body></s:Envelope>
    """
    context = RequestContext.from_xml(xml)
    assert (context.action, context.message_id) == ("Fallback", "plain-id")
    assert context.enumeration_context == "pull-id"
    assert context.max_elements is None


# Verifies malformed envelopes retain the public error contract.
def test_malformed_xml_is_wrapped_as_a_value_error() -> None:
    with pytest.raises(ValueError, match="^Failed to parse request XML:"):
        RequestContext.from_xml("<Envelope>")
