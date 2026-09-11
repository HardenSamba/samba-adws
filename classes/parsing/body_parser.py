import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Optional

from src.soap.namespaces import AD, ADDATA, CUSTOM_ACTIONS, DA

from classes.parsing.attribute_parser import AttributeParser
from classes.parsing.xml_chars import restore_tree

NS = {
    "s": "http://www.w3.org/2003/05/soap-envelope",
    "a": "http://www.w3.org/2005/08/addressing",
    "da": DA,
    "ad": AD,
    "addata": ADDATA,
    "ca": CUSTOM_ACTIONS,
}


# Reads the body of one request: the IMDA change lists and the custom-action
# elements the handlers ask for, from the tree with every character restored.
class BodyParser:

    # Parses the request text once; every reader below works on that tree.
    def __init__(self, xml_text: str) -> None:
        self.root = restore_tree(ET.fromstring(xml_text))

    # The attribute changes of an IMDA AddRequest, or None when there is none.
    def find_add_request(self) -> Optional[List[Dict[str, Any]]]:
        elem = self.root.find(".//da:AddRequest", NS)
        if elem is None:
            return None
        return AttributeParser.parse_changes(elem, default_op="add")

    # The attribute changes of an IMDA ModifyRequest, or None when there is none.
    def find_modify_request(self) -> Optional[List[Dict[str, Any]]]:
        elem = self.root.find(".//da:ModifyRequest", NS)
        if elem is None:
            return None
        return AttributeParser.parse_changes(elem, default_op=None, use_change=True)

    # The custom-action element of that name, whichever prefix the client used.
    def find_custom_body(self, element_name: str) -> Optional[ET.Element]:
        elem = self.root.find(f".//ca:{element_name}", NS)
        if elem is not None:
            return elem
        return self.root.find(f".//{{{CUSTOM_ACTIONS}}}{element_name}")

    # The text of one child of a custom-action element, or None when absent.
    def text_of(self, parent_elem: Optional[ET.Element], child_local_name: str) -> Optional[str]:
        if parent_elem is None:
            return None
        elem = parent_elem.find(f"ca:{child_local_name}", NS)
        if elem is None:
            elem = parent_elem.find(f"{{{CUSTOM_ACTIONS}}}{child_local_name}")
        return elem.text if elem is not None else None
