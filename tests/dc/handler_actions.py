#!/usr/bin/env python3
"""The action each registered handler is exercised with.

A literal map with no imports, so the coverage check can read it on a machine
that has no directory bindings. Keys are the registration keys of
HANDLER_FACTORIES; tests/unit/test_handler_coverage.py fails when the two
drift apart.

Values are the real protocol action where one is defined, and otherwise a
test-local `http://tests.invalid/<Key>` URI. That second form is not a claim
about what a Windows client sends: it is chosen because the router resolves an
unlisted action by its last path segment, so it reaches the handler under test
without inventing a Microsoft URI. A third such key, `Groups`, was removed
with GroupHandler; membership writes ride WS-Transfer Put instead. See
HardenSamba/samba-adws#4.
"""

TRANSFER = "http://schemas.xmlsoap.org/ws/2004/09/transfer"
ENUM = "http://schemas.xmlsoap.org/ws/2004/09/enumeration"
EVENTING = "http://schemas.xmlsoap.org/ws/2004/08/eventing"
CUSTOM = "http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
LOCAL = "http://tests.invalid"

HANDLER_ACTIONS = {
    "Get": f"{TRANSFER}/Get",
    "Put": f"{TRANSFER}/Put",
    "Delete": f"{TRANSFER}/Delete",
    "Create": f"{TRANSFER}/Create",
    "Enumerate": f"{ENUM}/Enumerate",
    "Pull": f"{ENUM}/Pull",
    "Release": f"{ENUM}/Release",
    "Renew": f"{ENUM}/Renew",
    "GetStatus": f"{ENUM}/GetStatus",
    "Subscribe": f"{EVENTING}/Subscribe",
    "Unsubscribe": f"{EVENTING}/Unsubscribe",
    "SubscriptionRenew": f"{EVENTING}/Renew",
    "SubscriptionStatus": f"{EVENTING}/GetStatus",
    "Notify": f"{CUSTOM}/AccountManagement/Notify",
    "ChangePassword": f"{CUSTOM}/AccountManagement/ChangePassword",
    "SetPassword": f"{CUSTOM}/AccountManagement/SetPassword",
    "TranslateName": f"{CUSTOM}/AccountManagement/TranslateName",
    "GetADGroupMember": f"{CUSTOM}/AccountManagement/GetADGroupMember",
    "GetADPrincipalGroupMembership":
        f"{CUSTOM}/AccountManagement/GetADPrincipalGroupMembership",
    "GetADPrincipalAuthorizationGroup":
        f"{CUSTOM}/AccountManagement/GetADPrincipalAuthorizationGroup",
    "GetADDomain": f"{CUSTOM}/TopologyManagement/GetADDomain",
    "GetADDomainController": f"{CUSTOM}/TopologyManagement/GetADDomainController",
    "GetADForest": f"{CUSTOM}/TopologyManagement/GetADForest",
    "GetVersion": f"{CUSTOM}/TopologyManagement/GetVersion",
    "MoveADOperationMasterRole":
        f"{CUSTOM}/TopologyManagement/MoveADOperationMasterRole",
    "ChangeOptionalFeature": f"{CUSTOM}/TopologyManagement/ChangeOptionalFeature",
    # No protocol action reaches these two: they match no operation in
    # [MS-ADCAP] and none in the WS-* tables. See samba-adws#4.
    "Schema": f"{LOCAL}/Schema",
    "Search": f"{LOCAL}/Search",
}
