"""Fusionne les chapitres en un document unique et allege les tics de redaction."""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CHAPTERS = os.path.join(HERE, "chapters")
OUTPUT = os.path.join(CHAPTERS, "complete.md")

PARTS = [
    ("00-guide-ultime", "Guide de référence des protocoles"),
    ("01-vue-ensemble", "Vue d’ensemble de la relation client-serveur"),
    ("02-nmf", "Le cadrage .NET Message Framing"),
    ("03-gssapi", "Authentification GSSAPI et Kerberos"),
    ("04-wcf", "L’encodage XML binaire"),
    ("05-soap", "SOAP, WS-Addressing et gestion des fautes"),
    ("06-operations", "Les opérations d’annuaire"),
    ("07-traces", "Traces de bout en bout et diagnostic"),
]

ROMAN = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII"]


# Isole les blocs de code afin de n'appliquer aucune reecriture a leur contenu.
def split_code(text: str) -> list[str]:
    return re.split(r"(```.*?\n.*?```)", text, flags=re.S)


# Decale tous les titres d'un niveau pour liberer le niveau 1 aux parties.
def demote(text: str) -> str:
    out = []
    for i, seg in enumerate(split_code(text)):
        if i % 2 == 1:
            out.append(seg)
            continue
        out.append(re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 1) + " ",
                          seg, flags=re.M))
    return "".join(out)


# -------------------------------------------------- allegement des tirets ---

PAIRED = re.compile(r"(?<=[^\s|])( +)—(\s+)(.{3,120}?)(\s+)—( +)(?=\S)", re.S)
TERM_DEF = re.compile(r"^(\s*(?:[-*]|\d+[.)])\s+.{2,90}?) +— +(?=\S)", re.M)
TRAILING = re.compile(r"(?<=[^\s|]) +— +(?=\S)")


# Remplace une incise encadree par des virgules, ou des parentheses si elle en contient.
def _incise(match: re.Match) -> str:
    inner = match.group(3)
    if "," in inner or ";" in inner:
        return f" ({inner}) "
    return f", {inner}, "


ITEM_RE = re.compile(r"^(\s*(?:[-*]|\d{1,2}[.)])\s+)")
OPAQUE_RE = re.compile(r"^\s*(?:\||#|```)")


# Vrai si la ligne ne peut pas etre fusionnee avec la precedente.
def _standalone(line: str) -> bool:
    return (not line.strip()) or bool(OPAQUE_RE.match(line)) or bool(ITEM_RE.match(line)) \
        or line.lstrip().startswith(">")


# Regroupe les lignes d'un meme paragraphe logique en (prefixe, texte).
def _logical_units(seg: str) -> list[tuple[str, str, bool]]:
    units: list[tuple[str, str, bool]] = []
    for line in seg.split("\n"):
        if not line.strip() or OPAQUE_RE.match(line):
            units.append(("", line, False))
            continue
        item = ITEM_RE.match(line)
        quote = line.lstrip().startswith(">")
        if quote:
            body = line.lstrip()[1:].strip()
            if units and units[-1][0] == "> ":
                units[-1] = ("> ", f"{units[-1][1]} {body}".strip(), True)
            else:
                units.append(("> ", body, True))
        elif item:
            units.append((item.group(1), line[item.end():], True))
        elif units and units[-1][2] and units[-1][0] != "> ":
            prefix, body, _ = units[-1]
            units[-1] = (prefix, f"{body} {line.strip()}", True)
        else:
            units.append(("", line.strip(), True))
    return units


# Reduit la densite de tirets cadratins sans alterer le sens.
def soften_dashes(text: str) -> str:
    import textwrap

    out = []
    for i, seg in enumerate(split_code(text)):
        if i % 2 == 1:
            out.append(seg)
            continue
        rendered: list[str] = []
        for prefix, body, mergeable in _logical_units(seg):
            if not mergeable:
                rendered.append(body)
                continue
            body = PAIRED.sub(_incise, body)
            if prefix and not prefix.startswith(">"):
                body = re.sub(r"^(.{2,90}?) +— +(?=\S)", r"\1 : ", body)
            body = TRAILING.sub(", ", body)
            body = re.sub(r"\s+—\s*([,;.])", r"\1", body)
            body = re.sub(r"^—\s*,?\s*", "", body)
            body = re.sub(r"\s+—\s*$", "", body)
            body = re.sub(r"\s{2,}", " ", body).strip()
            indent = " " * len(prefix) if prefix and not prefix.startswith(">") else \
                ("> " if prefix.startswith(">") else "")
            wrapped = textwrap.wrap(body, width=76 - len(prefix), break_long_words=False,
                                    break_on_hyphens=False) or [""]
            rendered.append(prefix + wrapped[0])
            rendered.extend(indent + w for w in wrapped[1:])
        out.append("\n".join(rendered))
    return "".join(out)


# ------------------------------------------------ puces numerotees natives ---

NUMBERED_BULLET = re.compile(r"^(\s*)- \*\*(\d{1,2})\.\*\* ", re.M)


def real_ordered_lists(text: str) -> str:
    out = []
    for i, seg in enumerate(split_code(text)):
        if i % 2 == 1:
            out.append(seg)
            continue
        out.append(NUMBERED_BULLET.sub(lambda m: f"{m.group(1)}{m.group(2)}. ", seg))
    return "".join(out)


# ------------------------------------------------------ tournures repetees ---

PHRASES = [
    (r"\bAutrement dit, ", "Dit autrement, "),
    (r"\bIl est essentiel de comprendre que\b", "Retenons que"),
    (r"\bIl convient de noter que\b", "On notera que"),
    (r"\bmérite une attention particulière\b", "appelle une remarque"),
    (r"\bmérite un développement\b", "demande une précision"),
    (r"\bmérite une mention particulière\b", "appelle une précision"),
    (r"\bmérite d’être signalé\b", "vaut d’être signalé"),
    (r"\bmérite une explication\b", "demande à être explicité"),
    (r"\bmérite un examen détaillé\b", "demande un examen détaillé"),
    (r"\bméritent attention\b", "appellent une remarque"),
    (r"\bIl s’agit là d’\b", "C’est "),
    (r"\bEn pratique, ", "Sur le terrain, "),
]


def vary_phrasing(text: str) -> str:
    out = []
    for i, seg in enumerate(split_code(text)):
        if i % 2 == 1:
            out.append(seg)
            continue
        for pattern, repl in PHRASES:
            seg = re.sub(pattern, repl, seg)
        out.append(seg)
    return "".join(out)


# ----------------------------------------------------------------- montage ---

def build() -> str:
    chunks: list[str] = []
    for index, (key, title) in enumerate(PARTS):
        path = os.path.join(CHAPTERS, key + ".md")
        with open(path, encoding="utf-8") as handle:
            body = handle.read().strip()
        body = real_ordered_lists(soften_dashes(vary_phrasing(demote(body))))
        chunks.append(f"# Partie {ROMAN[index]}. {title}\n\n{body}")
    return "\n\n".join(chunks) + "\n"


def main() -> int:
    text = build()
    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(text)
    prose = re.sub(r"```.*?```", "", text, flags=re.S)
    print(f"{OUTPUT}")
    print(f"  mots        : {len(text.split())}")
    print(f"  parties     : {len(re.findall(r'^# ', text, re.M))}")
    print(f"  niveau 2    : {len(re.findall(r'^## ', text, re.M))}")
    print(f"  niveau 3    : {len(re.findall(r'^### ', text, re.M))}")
    print(f"  tirets —    : {prose.count('—')}")
    print(f"  listes num. : {len(re.findall(r'^\\s*\\d+[.)] ', prose, re.M))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
