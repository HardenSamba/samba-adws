# Troubleshooting

Errors actually encountered in real runs, with their causes and their fixes.

## Index

| Symptom | Section |
|---|---|
| `STATUS_NO_SUCH_USER` on connect | [§ Kerberos / SPN](#1-kerberos--spn) |
| `Le site distant a fermé le flux de transport` | [§ Connection closed](#2-connection-closed-on-the-windows-side) |
| `Élément de fin '…' attendu, trouvé '…'` | [§ Malformed XML](#3-expected-end-element) |
| `[PULL] Error: __str__ returned non-string` | [§ MessageElement](#4-pull-error-__str__-returned-non-string) |
| `[ENUMERATE] Search failed: empty base DN` | [§ Empty base DN](#5-empty-base-dn) |
| Cmdlet hangs until the timeout | [§ Missing RelatesTo](#6-cmdlet-hangs) |
| `Unable to find a default server` / ADAC does not connect (`1355`) | [§ ADWS discovery](#7-unable-to-find-a-default-server) |
| Mutations refused | [§ Insufficient rights](#8-insufficient-rights) |
| Write with accented characters → `ADServerDownException` / `undefined entity` | [§ Non-ASCII characters](#9-non-ascii-characters-in-a-write) |
| A connection drops with no fault, log says `[LIMIT]` | [§ Announced size](#10-a-connection-is-closed-on-the-announced-size) |

---

## 1. Kerberos / SPN

### Symptom

On the server side, in the logs:

```
[SECURITY] ✗ Error: (3221225572, 'The specified account does not exist.')
Traceback (most recent call last):
  ...
  File ".../src/nettcp/stream/gssapi.py", line 119, in update
    ...
samba.NTSTATUSError: (3221225572, 'The specified account does not exist.')
```

`3221225572` = `0xC0000064` = `STATUS_NO_SUCH_USER`.

On the Windows side, the first cmdlet (typically `Get-ADRootDSE`) fails with:

```
The remote endpoint has terminated the transport stream
```

### Cause

The Kerberos ticket presented by the client targets an **SPN that is not registered** on the machine account of the DC. Samba cannot derive the key to decrypt it.

### Check

```bash
sudo samba-tool spn list "$(hostname -s)$"
```

The list must contain at least **`host/<fqdn>`**.

### Fix

```bash
sudo samba-tool spn add "host/$(hostname -f)" "$(hostname -s)$"
sudo samba-tool spn add "HOST/$(hostname -f)" "$(hostname -s)$"
```

On the Windows side, purge the ticket cache to force a new request:

```powershell
klist purge
```

> **Warning:** a clock skew between Windows and the DC (> 5 minutes) produces the **same** error. Check `timedatectl status` on the DC and `w32tm /query /status` on Windows.

---

## 2. Connection closed on the Windows side

### Symptom

```
Get-ADUser : Le site distant a fermé le flux de transport.
```

### Possible causes

1. **GSSAPI error** during the preamble (see [§ 1](#1-kerberos--spn)).
2. **Handler crash** on the server side: the dispatcher layer normally converts it into a SOAP fault, but an exception in the WCF/NMF layer cuts the raw connection.
3. **Firewall** closing the connection after a delay.

### Diagnosis

On the DC:

```bash
sudo journalctl -u samba-adws -n 200 --no-pager
```

Look for the last trace before the close. If it is a `Traceback`, this is a server bug; if it is `[CONNECTION CLOSED]` with no error, it is most likely a network issue.

---

## 3. Expected end element

### Symptom

On the Windows side, a PowerShell exception:

```
Élément de fin 'subSchema' attendu, trouvé 'ad:distinguishedName'
```

(or another element/objectClass pair, depending on the cmdlet)

### Cause

The server returned a response in **WS-Transfer mode** (`<addata:objectClass>...` wrapper) while the client asked for **IMDA mode** (each attribute in its own `<da:PartialAttribute>`). The AD parser on the Windows side applies the strict XML schema and rejects it.

### Fix

In the handler concerned, check `context.is_imda` and pick the right rendering:

```python
if context.is_imda:
    attributes_xml = self._render_attributes_for_imda(attributes)
    body_xml = f'<da:BaseObjectSearchResponse>{attributes_xml}</da:BaseObjectSearchResponse>'
else:
    attributes_xml = self._render_attributes_for_wst(attributes)
    body_xml = f'<addata:{obj_class}>{attributes_xml}</addata:{obj_class}>'
```

Also make sure `distinguishedName` is added as an explicit attribute (PowerShell requires it as the identity key even though LDB returns it through the `dn` property).

See [03-protocole.md § Get modes](03-protocole.md#modes-de-get--ws-transfer-vs-imda).

---

## 4. PULL Error: __str__ returned non-string

### Symptom

```
[PULL] Error: __str__ returned non-string (type NoneType)
```

### Cause

`str()` called on an empty or unusual `ldb.MessageElement`. Samba's C `__str__` method returns `None` in some cases → `TypeError`.

This typically happens with:

```python
class_val = val[0] if isinstance(val, list) else val   # MessageElement is not a list
object_class = str(class_val)                          # boom if __str__ returns None
```

### Fix

Explicitly unwrap the `MessageElement` into `bytes`, then decode:

```python
try:
    last_raw = val[-1] if hasattr(val, '__getitem__') and len(val) > 0 else val
except (IndexError, TypeError):
    last_raw = None

if isinstance(last_raw, bytes):
    object_class = last_raw.decode('utf-8', errors='replace')
elif last_raw is not None:
    try:
        object_class = str(last_raw)
    except TypeError:
        object_class = 'top'
```

The same applies anywhere an LDB attribute value is consumed: **always** assume you get a `MessageElement`, not a `list`.

---

## 5. Empty base DN

### Symptom

```
[ENUMERATE] Search failed: (32, 'empty base DN at .../partition.c:821')
```

### Cause

The client sends an empty `<adlq:BaseObject>`. This is legal for PowerShell ("search the whole default naming context") but Samba LDB refuses a search without a base DN.

### Fix

In `enumerate.py`, fall back to the naming context:

```python
base_dn = context.base_dn or ''
if not base_dn:
    base_dn = self.db.naming_context() or ''
```

---

## 6. Cmdlet hangs

### Symptom

`Get-ADUser` never returns, or returns after a long delay (`Operation timed out`).

### Common cause

The server returned a **SOAP fault without `<a:RelatesTo>`**. Without that header, the PowerShell client believes the message is an unsolicited response and ignores it → the cmdlet keeps waiting.

### Check

Enable message logging:

```bash
sudo journalctl -u samba-adws -f | grep -E "fault|RelatesTo"
```

### Fix

`SoapEnvelope.fault()` has always injected `<a:RelatesTo>{relates_to}</a:RelatesTo>`. The header went out empty because the value did, and this section used to prescribe exactly the line that emptied it:

```python
relates_to = context.message_id if context else ""      # the defect
```

`context` is `None` whenever the failure happened **before** the request was parsed — a WCF decode error, or XML that does not parse — which is precisely when a fault is most needed. `dispatcher._fault()` now takes the decoded request text as well as the context, and recovers the identifier from the text when there is no context:

```python
if context is not None:
    return SoapEnvelope.fault(context.message_id, "s:Receiver", message)
relates_to = message_id.extract(request)                 # tolerant of unparseable text
```

`classes/parsing/message_id.py` scans for a `MessageID` element under any prefix without requiring a parseable document. It reads at most the first 8 KB and returns nothing for a value over 256 characters: its input is chosen by the peer and its output goes into a response header.

### The case where nothing can be recovered

If the payload cannot be WCF-decoded at all, there is no text to scan and no identifier anywhere. **The connection is closed rather than answered.** A fault with an empty `RelatesTo` is discarded by the client, which then waits for its own timeout — the very symptom this section describes — so sending one is worse than sending nothing. A closed connection surfaces immediately.

The log says which of the two happened, and for whom:

```
[DISPATCH] 10.0.0.5:52344 sent a request that did not parse; faulting with the MessageID recovered from its text
[DISPATCH] 10.0.0.5:52344 sent a request with no recoverable MessageID; closing rather than sending a fault the client would discard
```

An [MC-NMF] `FaultRecord` was the alternative, and it is not used here: the specification defines no fault name for an undecodable envelope body, and inventing one under a private namespace would tell the client no more than the close does.

### A request that legitimately omits MessageID

WS-Addressing permits it, and such a request parses, so it has a context and takes the first branch above with an empty `relates_to`. That is unchanged and deliberate; it is not the defect described here.

---

## 7. Unable to find a default server

### Symptom

```
Get-ADUser : Unable to find a default server with Active Directory Web Services running.
```

### Causes: the simple cases first

1. The `samba-adws` service is not listening (check with `ss -tlnp | grep 9389`).
2. A firewall blocking 9389/tcp from the client.
3. Client DNS not pointing at the Samba DC (the DC locator needs the SRV records).

### Underlying cause: the Samba `DS_WS` limitation (ADAC + cmdlets WITHOUT `-Server`)

If everything above is fine (service up, port reachable, `nltest /dsgetdc` OK) but **automatic
discovery** still fails, typically with **ADAC** and with cmdlets run **without `-Server`**, this
is a **Samba limitation**, not a bug in this project.

Discovery in the AD module and in ADAC does not issue a plain "find a DC" call: it calls the
DC locator with the **`DS_WEB_SERVICE_REQUIRED`** flag ("only return a DC **if it advertises
that it runs ADWS**"). However, **Samba does not set the `DS_WS` flag (`NBT_SERVER_ADS_WEB_SERVICE`,
0x2000) in its Netlogon/CLDAP response**. This project provides the ADWS *service* (TCP 9389) but
cannot change Samba's CLDAP advertisement (UDP 389). The result is `ERROR_NO_SUCH_DOMAIN (1355)` /
`ADServerDownException`, **even though ADWS is running and answering** (a direct `-Server` connection works).

### Decisive diagnosis

```powershell
nltest /dsgetdc:samba.local        # OK  -> the DC can be located (DNS is fine)
nltest /dsgetdc:samba.local /ws    # 1355 -> Samba does not advertise ADWS = THE cause
Test-NetConnection 192.168.141.10 -Port 9389   # True -> the service does answer
```

If `/ws` fails while the call without `/ws` succeeds, this is the `DS_WS` limitation. **Nothing to fix on the
server side.**

### Workarounds

- **PowerShell**: always pass **`-Server <DC>`** (this short-circuits discovery), the supported and
  validated path. Set `$PSDefaultParameterValues` once (see [README](../README.md)).
- **Graphical console**: use **ADUC (`dsa.msc`)**, which speaks **LDAP** directly to Samba and uses
  **neither** ADWS **nor** flag-based discovery. It works where ADAC is blocked.
- **ADAC**: requires the `DS_WS` flag. Unblocking it would mean **patching and rebuilding Samba**
  (setting `NBT_SERVER_ADS_WEB_SERVICE` in `source4/cldap_server/netlogon.c`), which is heavy,
  fragile, and not advisable on a production DC managed by apt. **No `smb.conf` option** enables
  it.

---

## 8. Insufficient rights

### Symptom

```
Set-ADUser : Insufficient access rights to perform the operation
```

or, on the server side:

```
[CRUD] InsufficientAccessRights: ...
```

### Cause

For a **write**, this error now reflects the caller's real rights.
[Issue #8](https://github.com/HardenSamba/samba-adws/issues/8) opens the
request-time `SamDB` under the caller's GSSAPI session, so Samba's local `acl`
module denies a create, modify, delete, rename or password reset the principal
lacks the right for — the same result as direct LDAP. An `InsufficientAccessRights`
on a write is therefore a genuine authorization decision, not an artefact.

For a **read**, the error is still not a reliable rights signal.
[Issue #17](https://github.com/HardenSamba/samba-adws/issues/17) tracks the one
remaining gap: Samba applies read-side ACL filtering (`acl_read`) in its LDAP
frontend, not on a directly opened local `SamDB`, so a read runs as the caller
but is not attribute-filtered. A successful read may return attributes the
caller's ACLs would hide over LDAP. That is expected behaviour today, not a bug
to report.

### Fix

- Writes: the ADWS result matches direct LDAP for the same principal. Confirm the
  expected outcome over LDAP to distinguish an ACL denial from a schema or
  constraint error:

  ```bash
  ldbedit -H ldap://samba.local -U the.caller \
          -b "CN=cible,CN=Users,DC=samba,DC=local"
  ```

- Reads: do not infer read rights from ADWS output until #17 is resolved; check
  the expected attribute visibility over LDAP as the same principal
  (`ldbsearch -k yes -H ldap://<dc>`). A read that ADWS returns and `ldbsearch`
  hides is the known #17 gap, not a new fault.

- The server log names who each connection ran as:

  ```
  [SECURITY] 10.0.0.7:51322 authenticated as EXAMPLE\m.dupont
  ```

  If that line is missing, the connection was refused before anything was
  dispatched: the negotiation produced no session. That is a different problem
  from a denied write, and it is logged as one.

---

## 9. Non-ASCII characters in a write

### Symptom

A read (`Get-AD*`) works, but a write (`Set-ADUser`, `New-ADUser`, …)
in which **a value contains an accented character** (`créé`, `Ingénieur`, `Société`) fails on the Windows side:

```
Set-ADUser : Impossible de contacter le serveur. Il se peut que le serveur n'existe pas,
est actuellement hors service ou ne dispose pas des services Web Active Directory.
    + FullyQualifiedErrorId : ActiveDirectoryServer:0,...Commands.SetADUser
```

(`ADServerDownException`), while the server is listening and answering reads. On the DC:

```bash
sudo journalctl -u samba-adws -n 50 --no-pager | grep -A2 DISPATCH
```

```
[DISPATCH] unexpected failure
xml.etree.ElementTree.ParseError: undefined entity: line N, column M
ValueError: Failed to parse request XML: undefined entity
```

### Cause

When **decoding** the binary WCF request into XML text, the `escape()` function of the
vendored library (`src/wcf/records/text.py`) converted **every** character present in
`html.entities.codepoint2name` into a **named HTML entity**: `é` → `&eacute;`, `à` → `&agrave;`…
XML, however, predefines only **five** entities (`lt gt amp quot apos`). `créé` produced
`cr&eacute;&eacute;`, and `ET.fromstring()` (in [`classes/parsing/context.py`](../classes/parsing/context.py))
raised `undefined entity`. The exception propagated, the `ForkingTCPServer` child process died,
the connection was cut → the client reports this as `ADServerDownException`. Reads went
through because they do not send accented values.

### Fix

Map only the entities that are **valid in XML**; leave every other code point literal
(the decoded XML text is already a Unicode `str`, and `ElementTree` handles `é` natively):

```python
# src/wcf/records/text.py
_XML_ENTITY_BY_CP = {0x3C: '&lt;', 0x3E: '&gt;', 0x26: '&amp;', 0x22: '&quot;'}

def escapecp(cp):
    return _XML_ENTITY_BY_CP.get(cp, chr(cp))
```

Both the UTF-8 `Chars*` and UTF-16 `UnicodeChars*` record families must call
this escape function when reconstructing XML. The Linux client encoder uses
`UnicodeChars*` for ordinary text, including distinguished names; omitting the
call there would turn a valid `&amp;` back into a bare `&` and produce malformed
SOAP on the server.

Verified end to end: `Set-ADUser demo -Description 'créé via ADWS souverain'
-Replace @{title='Ingénieur Réseau'}` succeeds and the values round-trip intact.

---

## 10. A connection is closed on the announced size

### Symptom

The client's connection drops without an error message from the server, and the
log carries one line:

```
[LIMIT] 10.0.0.5:52344 announced 4294967296 bytes, maximum is 1048576
[LIMIT] 10.0.0.5:52344 refused and disconnected: announced length 4294967296 exceeds maximum 1048576
```

Or, when the length was not a plausible number at all:

```
[MESSAGES] ✗ Error: varint longer than 5 bytes
```

### Cause

Every length a peer announces is bounded before it is read, so that an
unauthenticated client cannot make the server allocate an arbitrary amount of
memory by announcing a large one. The ceiling is `ADWS_MAX_MESSAGE_SIZE` in
`/etc/default/samba-adws`, 1 MB by default. The connection is closed rather than
answered with a SOAP fault: the violation is detected below the message layer,
where there is no `MessageID` to put in a `RelatesTo`, and a fault without one
is ignored by the client anyway (§ 6).

### Fix

If the client is hostile or broken, nothing to do: this is the control working.

If a legitimate request is being refused, the request is genuinely larger than
1 MB. That is unusual — the ceiling bounds the **request**, not the response, so a
large `Get-ADUser -Filter *` result is unaffected. A write of a very large
attribute value can reach it. Raise the ceiling and restart:

```bash
sudo sed -i 's/^ADWS_MAX_MESSAGE_SIZE=.*/ADWS_MAX_MESSAGE_SIZE=4194304/' /etc/default/samba-adws
sudo systemctl restart samba-adws
```

The value only takes effect on restart. Windows ADWS applies the same 1 MB
default, so a request refused here is a request a Windows domain controller
would also refuse.

---

## Enabling more logs

By default the server logs at `INFO`. To make it verbose, change this in [`classes/server/config.py`](../classes/server/config.py):

```python
@dataclass
class LogConfig:
    level: int = logging.DEBUG     # instead of logging.INFO
```

Then restart:
```bash
sudo systemctl restart samba-adws
```

The log outputs are:
- `adws.log` (file in the launch directory, rotation 10 MB × 5)
- `journalctl -u samba-adws` (when run as a service)

---

## Capturing a full exchange for analysis

```bash
# 1. Raw capture
sudo tcpdump -i any -w /tmp/adws.pcap port 9389

# 2. Reproduce the error from Windows
# Get-ADUser ... -Server samba.local

# 3. Stop tcpdump

# 4. Enable the debug proxy to see the plaintext XML (before encryption):
# In tools/work/proxy.py:
# RECORD_LOG = "/tmp/adws-records.log"
```

The `.pcap` shows the TCP/NMF frames (GSSAPI-encrypted from phase 3 onwards), while `RECORD_LOG` shows the plaintext application XML for each message.
