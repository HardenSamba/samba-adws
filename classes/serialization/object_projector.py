import html
from typing import Any, Dict

from classes.serialization.xml_renderer import AttributeRenderer

# [MS-ADDM] synthetics: rendered in the ad: namespace with NO LdapSyntax,
# never through the addata: attribute renderer. Samba may also return
# distinguishedName as a plain attribute; filtering it here de-dupes it.
SYNTHETIC_KEYS = frozenset((
    "distinguishedname", "relativedistinguishedname",
    "objectreferenceproperty", "containerhierarchyparent",
))


class ObjectProjector:

    def __init__(self, renderer: AttributeRenderer) -> None:
        self.renderer: AttributeRenderer = renderer

    def whole_object(
        self, attributes: Dict[str, Any], obj_class: str, guid: str, dn: str
    ) -> str:
        attrs_xml = self.renderer.render_attributes(self._normal(attributes))
        ref_xml = self._synthetic("objectReferenceProperty", guid) if guid else ""
        rdn = dn.split(",")[0] if dn else ""
        tail = self._synthetic("relativeDistinguishedName", rdn)
        tail += self._synthetic("distinguishedName", dn)
        return f"<addata:{obj_class}>{ref_xml}{attrs_xml}{tail}</addata:{obj_class}>"

    def imda_projection(self, attributes: Dict[str, Any], dn: str) -> str:
        attrs_xml = self.renderer.render_attributes(
            self._normal(attributes), wrap_partial=True
        )
        dn_syn = self._synthetic("distinguishedName", dn)
        return (
            "<da:BaseObjectSearchResponse>"
            f"{attrs_xml}<da:PartialAttribute>{dn_syn}</da:PartialAttribute>"
            "</da:BaseObjectSearchResponse>"
        )

    @staticmethod
    def _normal(attributes: Dict[str, Any]) -> Dict[str, Any]:
        return {
            k: v for k, v in attributes.items()
            if k.lower() not in SYNTHETIC_KEYS
        }

    @staticmethod
    def _synthetic(name: str, value: str) -> str:
        return (
            f'<ad:{name}><ad:value xsi:type="xsd:string">'
            f"{html.escape(value)}</ad:value></ad:{name}>"
        )
