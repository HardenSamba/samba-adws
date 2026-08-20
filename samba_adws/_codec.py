"""Adapters around the repository's WCF binary XML codecs."""

from io import BytesIO, StringIO

from samba_adws.errors import ADWSClientError
from src.wcf.records import Record, dump_records, print_records
from src.wcf.xml2records import XMLParser


# Tracks short fixed-size reads while allowing the parser's final EOF probe.
class _ResponseStream(BytesIO):
    # Initializes the stream and its short-read observations.
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.short_reads: list[tuple[int, int, int]] = []

    # Records every fixed-size read that returned fewer bytes than requested.
    def read(self, size: int | None = -1) -> bytes:
        offset = self.tell()
        value = super().read(size)
        if size is not None and size >= 0 and len(value) < size:
            self.short_reads.append((offset, size, len(value)))
        return value


# Encodes SOAP XML with the static WCF dictionary marker.
def encode_xml(xml: str) -> bytes:
    try:
        return b"\x00" + bytes(dump_records(XMLParser.parse(xml)))
    except Exception as error:
        raise ADWSClientError("Failed to encode the ADWS request", "EncodingError") from error


# Decodes a static-dictionary WCF payload into SOAP XML.
def decode_xml(payload: bytes) -> str:
    try:
        stream = _ResponseStream(payload)
        if stream.read(1) != b"\x00":
            raise ADWSClientError(
                "Dynamic WCF dictionaries are not supported", "MalformedResponse"
            )
        records = Record.parse(stream, strict=True)
        expected_eof = [(len(payload), 1, 0)]
        if stream.short_reads != expected_eof:
            raise ADWSClientError("Truncated WCF response", "MalformedResponse")
        output = StringIO()
        print_records(records, fp=output)
    except ADWSClientError:
        raise
    except Exception as error:
        raise ADWSClientError("Malformed WCF response", "MalformedResponse") from error
    if not output.getvalue().strip():
        raise ADWSClientError("The ADWS response was empty", "MalformedResponse")
    return output.getvalue()
