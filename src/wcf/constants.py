import re

# Types pour le typage
from typing import Pattern

INTERESTING_NORMAL: Pattern = re.compile('[&<]')
INTERESTING_CDATA: Pattern = re.compile(r'<(/|\Z)')
INCOMPLETE: Pattern = re.compile('&[a-zA-Z#]')

ENTITYREF: Pattern = re.compile('&([a-zA-Z][-.a-zA-Z0-9]*)[^a-zA-Z0-9]')
CHARREF: Pattern = re.compile('&#(?:[0-9]+|[xX][0-9a-fA-F]+)[^0-9a-fA-F]')

STARTTAGOPEN: Pattern = re.compile(r'<[a-zA-Z][-.a-zA-Z0-9:_]*')
PICLOSE: Pattern = re.compile('>')
COMMENTCLOSE: Pattern = re.compile(r'--\s*>')
TAGFIND: Pattern = re.compile(r'([a-zA-Z][-.a-zA-Z0-9:_]*)(?:\s|/(?!>)|(?:(?<=["\'])\s*))')
ATTRFIND: Pattern = re.compile(
    r'\s*([a-zA-Z_][-.:a-zA-Z_0-9]*)(\s*=\s*'
    r'(\'[^\']*\'|"[^"]*"|[^\s"\'=<>`]*))?')

LOCATESTARTTAGEND: Pattern = re.compile(r"""
  <[a-zA-Z][-.a-zA-Z0-9:_]*
  (?:\s+
    (?:[a-zA-Z_][-.:a-zA-Z0-9_]*
      (?:\s*=\s*
        (?:'[^']*'
          |\"[^\"]*\"
          |[^'\">\s]+
         )
       )?
     )
   )*
  \s*
""", re.VERBOSE)

ENDTAGFIND: Pattern = re.compile(r'</\s*([a-zA-Z][-.a-zA-Z0-9:_]*)\s*>')