from typing import Any, Dict, List, Optional, Sequence, Tuple, cast

from classes.parsing.body_parser import BodyParser
from classes.serialization.ca_elements import CaElement
from classes.parsing.context import RequestContext
from classes.serialization.name_formats import NameFormatResolver
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler

_STATUS_CODE: Dict[str, str] = {"Found": "0", "NotFound": "2", "NoMapping": "4"}

_RESULT_PLAN: Sequence[Tuple[str, str, str]] = (
    ("text", "Name", "name"),
    ("text", "Result", "result"),
)


class TranslateNameHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/TranslateNameResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            names, fmt_offered, fmt_desired = self._extract(context)
            resolver = NameFormatResolver(self.db, self.logger)
            translated = [
                resolver.translate(cast(str, n), fmt_offered, fmt_desired) for n in names
            ]
            body = self._serialize_results(translated)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[TranslateName] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "TranslateNameFault", str(e)
            ))

    @staticmethod
    def _extract(
        context: RequestContext,
    ) -> Tuple[List[Optional[str]], str, str]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("TranslateNameRequest")
        if body is None:
            return [], "Unknown", "DistinguishedName"
        ns_uri = "http://schemas.microsoft.com/2008/1/ActiveDirectory/CustomActions"
        names_elem = body.find(f".//{{{ns_uri}}}Names")
        names: List[Optional[str]] = (
            [c.text for c in list(names_elem)] if names_elem is not None else []
        )
        fmt_offered: str = parser.text_of(body, "FormatOffered") or "Unknown"
        fmt_desired: str = parser.text_of(body, "FormatDesired") or "DistinguishedName"
        return names, fmt_offered, fmt_desired

    @staticmethod
    def _serialize_results(translated: List[Dict[str, Any]]) -> str:
        items = "".join(TranslateNameHandler._item(t) for t in translated)
        return CaElement.response("TranslateNameResponse", "NameTranslateResult", items)

    @staticmethod
    def _item(entry: Dict[str, Any]) -> str:
        data = {
            "name": entry.get("result", ""),
            "result": _STATUS_CODE.get(entry.get("status", ""), "2"),
        }
        return (
            "<ActiveDirectoryNameTranslateResult>"
            f"{CaElement.fields(_RESULT_PLAN, data)}"
            "</ActiveDirectoryNameTranslateResult>"
        )
