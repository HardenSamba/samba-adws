# ADWS handlers

One handler = one file in [classes/handlers/](../classes/handlers/). It processes **a single SOAP action**.

## Catalogue

### WS-Transfer (single object)

| SOAP action | Handler | Typical PowerShell cmdlet |
|---|---|---|
| `…/transfer/Get` | [`get.py`](../classes/handlers/get.py) — `GetHandler` | `Get-ADUser`, `Get-ADRootDSE`, `Get-ADObject` |
| `…/transfer/Put` | [`transfer.py`](../classes/handlers/transfer.py) — `TransferHandler` | `Set-ADUser` (DN-based form) |
| `…/transfer/Delete` | [`transfer.py`](../classes/handlers/transfer.py) | `Remove-ADUser` |
| `…/transfer/Create` | [`crud.py`](../classes/handlers/crud.py) — `CRUDHandler` | `New-ADUser`, `New-ADGroup` |

### WS-Enumeration (paginated search)

| SOAP action | Handler | Description |
|---|---|---|
| `…/enumeration/Enumerate` | [`enumerate.py`](../classes/handlers/enumerate.py) — `EnumerateHandler` | Starts an enumeration session, runs `samdb.search()`, stores the results under a UUID |
| `…/enumeration/Pull` | [`pull.py`](../classes/handlers/pull.py) — `PullHandler` | Pulls a batch of objects from the UUID context |
| `…/enumeration/Release` | [`release.py`](../classes/handlers/release.py) — `ReleaseHandler` | Releases the context on the server side |
| `…/enumeration/Renew` | [`renew.py`](../classes/handlers/renew.py) — `RenewHandler` | Extends the context expiration |
| `…/enumeration/GetStatus` | [`get_status.py`](../classes/handlers/get_status.py) — `GetStatusHandler` | Context status and expiration |

### ADWS-specific actions

| Action (URL suffix) | Handler | Associated cmdlet |
|---|---|---|
| `Search` | [`search.py`](../classes/handlers/search.py) | arbitrary IMDA searches |
| `Schema` | [`schema.py`](../classes/handlers/schema.py) | class and attribute introspection |
| `Groups` | [`groups.py`](../classes/handlers/groups.py) | bulk group operations |
| `GetADGroupMember` | [`get_ad_group_member.py`](../classes/handlers/get_ad_group_member.py) | `Get-ADGroupMember` |
| `GetADPrincipalGroupMembership` | [`get_ad_principal_group_membership.py`](../classes/handlers/get_ad_principal_group_membership.py) | `Get-ADPrincipalGroupMembership` |
| `GetADPrincipalAuthorizationGroup` | [`get_ad_principal_authorization_group.py`](../classes/handlers/get_ad_principal_authorization_group.py) | `Get-ADPrincipalAuthorizationGroup` (recursive token groups) |
| `SetPassword` | [`set_password.py`](../classes/handlers/set_password.py) | `Set-ADAccountPassword -Reset` |
| `ChangePassword` | [`change_password.py`](../classes/handlers/change_password.py) | `Set-ADAccountPassword` (with the old password) |
| `TranslateName` | [`translate_name.py`](../classes/handlers/translate_name.py) | DN ↔ NT4 ↔ UPN ↔ canonical conversion |
| `GetADDomain` | [`get_ad_domain.py`](../classes/handlers/get_ad_domain.py) | `Get-ADDomain` |
| `GetADDomainController` | [`get_ad_domain_controller.py`](../classes/handlers/get_ad_domain_controller.py) | `Get-ADDomainController` |
| `GetADForest` | [`get_ad_forest.py`](../classes/handlers/get_ad_forest.py) | `Get-ADForest` |
| `GetVersion` | [`get_version.py`](../classes/handlers/get_version.py) | ADWS version number |
| `MoveADOperationMasterRole` | [`move_operation_master_role.py`](../classes/handlers/move_operation_master_role.py) | `Move-ADDirectoryServerOperationMasterRole` (FSMO transfer/seize) |
| `ChangeOptionalFeature` | [`change_optional_feature.py`](../classes/handlers/change_optional_feature.py) | `Enable-ADOptionalFeature` |

### Internal CRUD

| File | Role |
|---|---|
| [`create.py`](../classes/handlers/create.py) — `CreateHandler` | Creation logic used by `CRUDHandler` |
| [`modify.py`](../classes/handlers/modify.py) — `ModifyHandler` | Modification logic used by `TransferHandler` (Put) |
| [`delete.py`](../classes/handlers/delete.py) — `DeleteHandler` | Deletion logic used by `TransferHandler` (Delete) |

## Routing

Action → handler map in [`src/handlers/handler_routing.py`](../src/handlers/handler_routing.py):

```python
ACTION_HANDLER_KEYS = {
    "http://schemas.xmlsoap.org/ws/2004/09/transfer/get":    "Get",
    "http://schemas.xmlsoap.org/ws/2004/09/transfer/create": "Create",
    …
}

HANDLER_FACTORIES = (
    ("Get",         GetHandler),
    ("Enumerate",   EnumerateHandler),
    …
)
```

`HandlerRegistry.resolve(action)`:

1. First looks for an **exact**, case-insensitive match in `ACTION_HANDLER_KEYS`.
2. Failing that, takes the **last segment** of the URL (`http://…/Foo/Bar` → `Bar`) and looks it up in `HANDLER_FACTORIES`.

This is what lets the ADWS-specific actions (Microsoft proprietary URLs) reach the right handler through a simple naming convention.

## Handler contract

They all inherit from [`BaseHandler`](../classes/handlers/base.py):

```python
class BaseHandler:
    def __init__(self, logger, session_info=None):
        self.logger = logger
        self.session_info = session_info

    def log_request(self, context: RequestContext) -> None: ...

    def handle(self, context: RequestContext) -> str:
        raise NotImplementedError
```

`handle()` must:

1. Read `context.action`, `context.message_id`, `context.base_dn`, `context.ldap_filter`, `context.is_imda`, and so on.
2. Perform the LDB operation through `samba.samdb`.
3. Return a **complete SOAP XML string** (envelope + headers + body).

The dispatcher takes care of:
- serializing XML → WCF records,
- prefixing with `\x00` (the WCF framing byte, **do not forget it**),
- converting exceptions into SOAP faults carrying `<a:RelatesTo>`.

## Adding a new handler

Example: implementing `GetADReplicationFailure`.

### 1. Create the file

`classes/handlers/get_ad_replication_failure.py`:

```python
from .base import BaseHandler
from classes.parsing.context import RequestContext


class GetADReplicationFailureHandler(BaseHandler):
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        body = self._build_body(context)
        return self.envelope.wrap(
            context.action + "Response", context.message_id, body)

    def _build_body(self, context: RequestContext) -> str:
        return "<adws:GetADReplicationFailureResponse xmlns:adws='…'/>"
```

> Follow the project rules: **5 functions max, 20 lines max per function, no comments**.

### 2. Export it

In [`classes/handlers/__init__.py`](../classes/handlers/__init__.py):

```python
from .get_ad_replication_failure import GetADReplicationFailureHandler
__all__ = [..., "GetADReplicationFailureHandler"]
```

### 3. Register it

In [`src/handlers/handler_routing.py`](../src/handlers/handler_routing.py):

```python
from classes.handlers import (..., GetADReplicationFailureHandler)

HANDLER_FACTORIES = (
    …
    ("GetADReplicationFailure", GetADReplicationFailureHandler),
)
```

Last-URL-segment routing does the rest: if PowerShell sends `Action=…/GetADReplicationFailure`, the handler is found.

### 4. Test

```powershell
Get-ADReplicationFailure -Server samba.local
```

And watch the logs on the DC:
```bash
sudo journalctl -u samba-adws -f | grep ReplicationFailure
```

## Frequently used helpers

In `classes/` and `src/` (organised by phase):

| Module | When to use it |
|---|---|
| `object_projector.ObjectProjector` | serializes a whole object (`whole_object` = WS-Transfer form / IMDA form b) or the IMDA form a projection (`imda_projection`). Shared by `get.py` and `pull.py` |
| `xml_renderer.AttributeRenderer` | renders a dict of LDB attributes into `<addata:{name} LdapSyntax="…">` (the `wrap_partial` option wraps each attribute in `<da:PartialAttribute>`) |
| `value_codec.ValueCodec` | per-syntax **value** encoding: string, integer, long, dateTime, boolean; anything binary (OctetString / SidString / NTSecurityDescriptor) → `xsd:base64Binary` |
| `syntaxes.SyntaxRegistry` | `syntax_for` (internal OID, drives value encoding) **and** `ldap_syntax_name_for` (`DirectorySyntaxType` enum name for the `LdapSyntax` attribute) |
| reading `nTSecurityDescriptor` | comes back as raw `base64Binary`, like the real ADWS; the SDDL codec on the write side is not wired up yet |
| `filter_parser.LdapFilterParser` | RFC 4515 LDAP parser (used mainly in `enumerate.py` and `search.py`) |
| `ldap_attr_builder.LdapAttributeBuilder` | builds LDB objects for Create/Modify |
| `domain_loader.DomainLoader` | cached domain information (DN, NetBIOS, GUID, …) |
| `principal_loader.PrincipalLoader` | `sAMAccountName` ↔ DN ↔ SID resolution |
| `instance_index.InstanceIndex` | AD `wsa:InstanceId` identifiers (`11111111-1111-1111-1111-111111111111`, …) |
| `typed_faults` + `fault_codes` | raise a typed `ADWSException` so that it surfaces with a standard MS code |

## Best practices

- **Always** raise an `ADWSException` (or one of its typed subclasses) rather than a bare `Exception`. The dispatcher will then know how to translate it into a correct SOAP fault.
- **Always** check `context.is_imda` before rendering objects: the wrong wrapper breaks the XML parser on the Windows side and the cmdlet returns `Site distant a fermé le flux`.
- **Always** add `distinguishedName` as an explicit attribute when rendering an object in IMDA (PowerShell requires it as the identity key).
- **Do not open** `SamDB` at module level: the server forks on every connection. Open it inside `handle()` or use `ldap_session_pool`, which handles this.
- For long operations (large enumerations), honour the Pull `MaxElements` limit and store the remainder in `enumeration.EnumerationContext`.

## Serialization wire format

All object serialization goes through `ObjectProjector`. The rules
below reproduce the format expected by the Windows client, as
defined by [MS-ADDM] and confirmed by the observed behaviour of the cmdlets.

### `LdapSyntax` attribute = enumeration name, never an OID

The `LdapSyntax` attribute carries the **member name** of the directory
syntax enumeration,
for example `UnicodeString`, `Integer`, `LargeInteger`, `Boolean`,
`GeneralizedTimeString`, `ObjectIdentifier`, `DSDNString`, `OctetString`,
`SidString`, `NTSecurityDescriptor`. Emitting an OID (`2.5.4.3`, …) makes
the conversion to the enumeration fail on the client side: PowerShell **rejects**
the response.
→ `SyntaxRegistry.ldap_syntax_name_for(attr)`.

### The value's `xsi:type` = type of the data carried

The `xsi:type` reflects the **type of the data** being carried, independently of the
LDAP syntax: a string → `xsd:string`, a global identifier →
`xsd:string` (canonical form), a byte sequence → `xsd:base64Binary`. Now
ADWS treats as binary every attribute whose syntax is **OctetString, SidString,
ReplicaLink or NTSecurityDescriptor**: `objectSid`, `objectGUID`,
`nTSecurityDescriptor`, `tokenGroups`, and so on therefore come out as `base64Binary`
holding **raw** binary (never an SDDL string or a textual GUID).
→ `ValueCodec._encode_binary`.

> `objectReferenceProperty` is the EPR (a global identifier) → `xsd:string` in
> canonical form. Not to be confused with the `objectGUID` attribute (base64).

### Synthetic attributes in the `ad:` namespace, without `LdapSyntax`

`distinguishedName`, `relativeDistinguishedName`, `objectReferenceProperty`,
`containerHierarchyParent` are rendered as `<ad:{name}><ad:value
xsi:type="xsd:string">…</ad:value></ad:{name}>`: the `ad:` namespace, **without**
`LdapSyntax`. They are filtered out of the normal attribute stream to avoid a
duplicate `<addata:distinguishedName>`. → `ObjectProjector.SYNTHETIC_KEYS`.

### IMDA Get: two forms, depending on the requested `AttributeType` elements

Discriminator: `context.is_imda and context.requested_attributes`
(see [MS-WSTIM], `BaseObjectSearchRequest` operation).

- **Form a** (at least one `AttributeType` requested), `imda_projection`: one
  `<da:PartialAttribute>` **per requested attribute**; `distinguishedName`
  always emitted (synthetic `ad:`). No `<addata:{class}>` wrapper.
- **Form b** (no `AttributeType`): the whole object inside **a single**
  `<da:PartialAttribute>` (`_wrap_imda_object` around `whole_object`).

### WS-Transfer Get and WS-Enumeration Pull items = whole object

`whole_object` produces `<addata:{structuralClass}>` =
`objectReferenceProperty` (when the GUID is known) + attributes + `relativeDistinguishedName`
+ `distinguishedName`. `Pull` items use **exactly** this
form (and not `PartialAttribute` elements). The Pull envelope must declare
`xsd` (the values carry `xsi:type="xsd:…"`).

### RootDSE

`Get-ADRootDSE` goes through WS-Transfer Get → `<addata:top>` +
`objectReferenceProperty = 11111111-1111-1111-1111-111111111111`. The
operational attributes have their own syntaxes (`namingContexts` and the like =
`DSDNString`, `supportedControl` = `ObjectIdentifier`, `currentTime` =
`GeneralizedTimeString`, `highestCommittedUSN` = `LargeInteger`,
`isSynchronized` = `Boolean`, …), listed in `syntax_constants.py`.
