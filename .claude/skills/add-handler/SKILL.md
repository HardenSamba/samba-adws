---
name: add-handler
description: >
  Scaffold a new ADWS SOAP action handler under classes/handlers and wire it
  into the routing, following project conventions (one class per file, typed,
  IMDA/WS-Transfer aware, typed faults). Use when adding support for a new
  PowerShell cmdlet, SOAP action, or WS-* operation — e.g. "add a handler for
  GetADReplicationFailure", "implement the X action", "support cmdlet Get-ADY".
argument-hint: <ActionName e.g. GetADReplicationFailure>
---

# Add an ADWS handler

Goal: create `classes/handlers/<snake>.py` with a single `BaseHandler`
subclass and register it. The SOAP action to implement is `$ARGUMENTS`
(ask the user if empty).

## 0. Reconnaissance
- Read `documentation/04-handlers.md` (the catalogue + routing rules).
- Read a close existing handler to copy its shape. Minimal example:
  `classes/handlers/get_version.py`. Object-rendering example (IMDA vs
  WS-Transfer): `classes/handlers/get.py`.
- Decide the routing key: the **last URL segment** of the SOAP action
  (`http://.../SomeNs/GetADReplicationFailure` -> `GetADReplicationFailure`).

## 1. Create the handler file
`classes/handlers/<snake_case>.py` — one class only:

```python
from .base import BaseHandler
from classes.parsing.context import RequestContext
from src.soap.namespaces import CUSTOM_ACTIONS


class <Name>Handler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/.../<Name>Response"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        body = self._build_body(context)
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)

    def _build_body(self, context: RequestContext) -> str:
        ...
```

Real APIs (verify against source, do not trust the doc which is stale on
this point):
- Response envelope: `self.envelope.wrap(action, relates_to, body_xml)`
  in `classes/soap/soap_envelope.py`. (There is **no** `.response(...)`.)
- `relates_to` MUST be `context.message_id` — without `<a:RelatesTo>` the
  cmdlet hangs until timeout.
- DB access only via `self.db` (a `SambaDB`, see `classes/directory/samba_db.py`):
  `self.db.search(...)`, `self.db.naming_context()`. NEVER open `SamDB` at
  module level (server is ForkingTCPServer; samba is not thread-safe).
- Errors: raise a typed `ADWSException` subclass from
  `classes/faults/exceptions.py` (e.g. `ADWSObjectNotFoundException`,
  `ADWSAccessDeniedException`) — never a bare `Exception`. The dispatcher
  turns it into a SOAP fault.

## 2. Object rendering (only if returning AD objects)
Branch on `context.is_imda`:
- IMDA: one `<da:PartialAttribute>` per attribute, and always include
  `distinguishedName` as an explicit attribute.
- WS-Transfer: a single `<addata:{objectClass}>` wrapper.
Use `self.renderer` (`AttributeRenderer`) / `self.codec` (`ValueCodec`).
A wrong wrapper makes the Windows XML parser reject the response.

## 3. Export it
`classes/handlers/__init__.py`: add `from .<snake> import <Name>Handler`
and append `"<Name>Handler"` to `__all__`.

## 4. Register routing
`src/handlers/handler_routing.py`:
- add `<Name>Handler` to the top `from classes.handlers import (...)` block;
- add `("<RoutingKey>", <Name>Handler)` to `HANDLER_FACTORIES`;
- if the action is an exact WS-* URL (transfer/enumeration/eventing), also
  add it to `ACTION_HANDLER_KEYS` (lowercased full URL -> key).

## 5. Conventions (enforced)
1 class & <=5 functions per file, functions <=20 lines, nesting <=2, full
type annotations, no comments. Run the `check-norms` skill on the new file.

## 6. Test & docs
- Add an isolated case (build a `RequestContext` by hand) — see
  `documentation/05-tests.md` (`test_handlers.py`, currently to be created).
- Add the action to the table in `documentation/04-handlers.md`.
- Final E2E: the matching cmdlet via `Test-ADWS-Sovereign.ps1`.
