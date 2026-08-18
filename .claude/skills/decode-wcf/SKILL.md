---
name: decode-wcf
description: >
  Decode a captured WCF binary (MS-NBFX) payload into readable XML for
  protocol debugging, using the project's src.wcf.records.dump_records. Use when
  investigating a malformed-response or parser error, analyzing a tcpdump /
  proxy capture, or when asked to "decode this payload", "what XML is in this
  frame", "dump these WCF records".
allowed-tools: Bash, Read
argument-hint: <path-to-binary | hex-string>
---

# Decode a WCF binary payload

Must run from the **repo root** (so `wcf` is importable).

## From a binary file

```bash
python3 -c "from src.wcf.records import dump_records; \
data=open('PAYLOAD.bin','rb').read(); print(dump_records(data))"
```

## From a hex string

```bash
python3 -c "from src.wcf.records import dump_records; \
data=bytes.fromhex('00 40 01 61 ...'.replace(' ','')); \
print(dump_records(data))"
```

## Gotchas
- The dispatcher prefixes application payloads with a single `\x00` framing
  byte (`_encode_response` in `classes/handlers/dispatcher.py`). If decoding fails
  on a captured outbound frame, retry with `data[1:]`.
- After the GSSAPI upgrade, on-wire bytes are **sealed**. A raw `tcpdump`
  capture won't decode — get the cleartext from the debug record log
  (`RECORD_LOG` in `tools/work/proxy.py`), per `documentation/03-protocole.md`.
- To go the other way (XML -> records) use `wcf.xml2records.XMLParser.parse`.

See `documentation/03-protocole.md` for the full framing/encoding model.
