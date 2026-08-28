"""The RootDSE answers this call cannot return one naming context out of.

There are two, and they are not the same failure: the attribute was not
published at all, or it was published carrying more than one value. Saying
"published none" for the second sends the reader to look at the directory for
a value that is sitting in the response.
"""

import functools

import pytest
from samba_adws import ADWSClient, ADWSClientError
from samba_adws._root_dse import ROOT_DSE_IDENTITY

from tests.client_helpers import install_transport, response_for

SOMETHING_ELSE = (
    '<da:BaseObjectSearchResponse><da:PartialAttribute>'
    '<addata:dnsHostName LdapSyntax="UnicodeString">'
    '<ad:value xsi:type="xsd:string">dc.example.test</ad:value>'
    '</addata:dnsHostName></da:PartialAttribute>'
    '</da:BaseObjectSearchResponse>'
)
MORE_THAN_ONE = (
    '<da:BaseObjectSearchResponse><da:PartialAttribute>'
    '<addata:namingContexts LdapSyntax="DSDNString">'
    '<ad:value xsi:type="xsd:string">DC=example,DC=test</ad:value>'
    '<ad:value xsi:type="xsd:string">CN=Configuration,DC=example,DC=test</ad:value>'
    '</addata:namingContexts></da:PartialAttribute>'
    '</da:BaseObjectSearchResponse>'
)


# A RootDSE that published no such attribute is refused rather than guessed at.
def test_a_missing_naming_context_is_a_typed_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_transport(monkeypatch, functools.partial(response_for, body=SOMETHING_ELSE))

    with pytest.raises(ADWSClientError) as failure:
        ADWSClient("dc.example.test").naming_context()

    assert failure.value.code == "MalformedResponse"
    assert failure.value.target == ROOT_DSE_IDENTITY
    assert "published no defaultNamingContext" in str(failure.value)


# An attribute carrying several contexts is refused, and says why.
#
# `namingContexts` is the multi-valued one, and it is what a caller reaching
# past the default asks for. It decodes to a tuple: returning its first value
# would hand back one context out of several with no way to tell, and reporting
# it as unpublished would blame a server that published it.
def test_several_contexts_are_refused_without_claiming_none_was_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_transport(monkeypatch, functools.partial(response_for, body=MORE_THAN_ONE))

    with pytest.raises(ADWSClientError) as failure:
        ADWSClient("dc.example.test").naming_context("namingContexts")

    assert failure.value.code == "MalformedResponse"
    assert "published no" not in str(failure.value)
    assert "namingContexts" in str(failure.value)
