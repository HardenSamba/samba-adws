import xml.parsers.expat
from typing import Optional, List, Tuple
from src.wcf.html_parse_error import HTMLParseError
from src.wcf.constants import INTERESTING_NORMAL, INTERESTING_CDATA

class HTMLParser:
    """Case-preserving XML parser replacing HTMLParser for WCF."""

    def __init__(self):
        self.rawdata = ""
        self.lasttag = "???"
        self.interesting = INTERESTING_NORMAL
        self.is_cdata = False
        self.data = None
        self._parser = None

    def reset(self):
        self.rawdata = ""
        self.lasttag = "???"
        self.interesting = INTERESTING_NORMAL
        self.is_cdata = False
        self.data = None
        
        # On n'utilise pas de séparateur de namespace pour qu'Expat 
        # nous retourne les tags complets (ex: "s:Envelope") 
        # tels que le client ADWS les attend.
        self._parser = xml.parsers.expat.ParserCreate()
        self._parser.StartElementHandler = self._start_element
        self._parser.EndElementHandler = self._end_element
        self._parser.CharacterDataHandler = self._char_data

    def feed(self, data):
        if self._parser is None:
            self.reset()
        try:
            if isinstance(data, bytes):
                data = data.decode('utf-8')
            self._parser.Parse(data, False)
        except Exception as e:
            raise HTMLParseError(str(e))

    def close(self):
        if self._parser is not None:
            try:
                self._parser.Parse("", True)
            except Exception:
                pass

    def error(self, message):
        raise HTMLParseError(message)

    def _start_element(self, name, attrs):
        # Expat fournit un dictionnaire, xml2records attend une liste de tuples
        attr_list = list(attrs.items())
        self.handle_starttag(name, attr_list)

    def _end_element(self, name):
        self.handle_endtag(name)

    def _char_data(self, data):
        self.handle_data(data)

    # Méthodes d'interface pour être compatibles avec wcf.xml2records.XMLParser
    def handle_starttag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        pass

    def handle_data(self, data):
        pass
        
    def handle_charref(self, name):
        pass
        
    def handle_entityref(self, name):
        pass

    def handle_decl(self, decl):
        pass

    def handle_comment(self, data):
        pass

interesting_cdata = INTERESTING_CDATA