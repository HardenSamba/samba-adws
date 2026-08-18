from typing import Any, Dict, Iterable, List, Optional, Set

from classes.serialization.syntaxes import SyntaxRegistry

SKIP_KEYS: Set[str] = {"dn", "dn_parsed"}


class AttributeRenderer:

    def __init__(self, syntaxes: SyntaxRegistry, codec: Any) -> None:
        self.syntaxes: SyntaxRegistry = syntaxes
        self.codec: Any = codec

    def render_attributes(
        self,
        attributes: Dict[str, Any],
        requested: Optional[Iterable[str]] = None,
        wrap_partial: bool = False,
    ) -> str:
        parts: List[str] = []
        wanted = self._normalize_request(requested)
        for name, raw in attributes.items():
            if name.lower() in SKIP_KEYS or name.startswith("_"):
                continue
            if wanted is not None and name.lower() not in wanted:
                continue
            attr_xml = self._render_one(name, raw)
            if not attr_xml:
                continue
            if wrap_partial:
                attr_xml = f"<da:PartialAttribute>{attr_xml}</da:PartialAttribute>"
            parts.append(attr_xml)
        return "".join(parts)

    def _render_one(self, name: str, raw: Any) -> str:
        values = self._listify(raw)
        rendered: List[str] = []
        for v in values:
            if v is None:
                continue
            xsd, encoded = self.codec.encode_to_xsd(name, v)
            rendered.append(f'<ad:value xsi:type="{xsd}">{encoded}</ad:value>')
        if not rendered:
            return ""
        ldap_syntax = self.syntaxes.ldap_syntax_name_for(name)
        return (
            f'<addata:{name} LdapSyntax="{ldap_syntax}">'
            f'{"".join(rendered)}</addata:{name}>'
        )

    @staticmethod
    def _listify(raw: Any) -> List[Any]:
        if raw is None:
            return []
        if isinstance(raw, (str, bytes)):
            return [raw]
        if hasattr(raw, "__iter__"):
            return list(raw)
        return [raw]

    @staticmethod
    def _normalize_request(requested: Optional[Iterable[str]]) -> Optional[Set[str]]:
        if not requested:
            return None
        result: Set[str] = set()
        for name in requested:
            cleaned = name
            if cleaned.startswith("addata:"):
                cleaned = cleaned[7:]
            elif cleaned.startswith("ad:"):
                cleaned = cleaned[3:]
            result.add(cleaned.lower())
        return result
