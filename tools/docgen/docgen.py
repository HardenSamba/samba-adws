"""Genere les PDF de documentation a partir du template SYNETIS et de chapitres Markdown."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import zipfile

import cover
import diagrams as diagram_lib
import docx
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Emu, Pt, RGBColor, Twips

SOFFICE = r"C:\Program Files\LibreOffice\program\soffice.exe"

RED = "ED1C24"
BAND = "E8E8E8"
CODE_PT = 8.0
INLINE_CODE_PT = 9.5
BULLET_NUMID = 42
ORDERED_ABSTRACT = 3

CONTENT_WIDTH_EMU = int(6.30 * 914400)
MAX_FIGURE_EMU = int(8.30 * 914400)
DIAGRAM_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build", "diagrams")

# ---------------------------------------------------------------- markdown ---

FENCE_RE = re.compile(r"^```\s*([A-Za-z0-9_:+-]*)\s*$")
HEAD_RE = re.compile(r"^(#{1,4})\s+(.*)$")
BULLET_RE = re.compile(r"^(\s*)-\s+(.*)$")
ORDERED_RE = re.compile(r"^(\s*)(\d{1,2})[.)]\s+(.*)$")
TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")


def split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def parse_md(text: str) -> list[tuple]:
    """Retourne une liste de blocs (kind, payload...)."""
    lines = text.replace("\r\n", "\n").split("\n")
    blocks: list[tuple] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue

        m = FENCE_RE.match(line.strip())
        if m:
            lang = m.group(1)
            i += 1
            buf = []
            while i < n and not FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i].rstrip("\n"))
                i += 1
            i += 1
            while buf and not buf[-1].strip():
                buf.pop()
            if lang.startswith("schema:"):
                blocks.append(("diagram", lang[len("schema:"):], " ".join(buf).strip()))
            else:
                blocks.append(("code", lang, buf))
            continue

        m = HEAD_RE.match(line)
        if m:
            blocks.append(("h", len(m.group(1)), m.group(2).strip()))
            i += 1
            continue

        # tableau : ligne avec pipes suivie d'une ligne de separation
        if "|" in line and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1]):
            header = split_row(line)
            i += 2
            rows = [header]
            while i < n and "|" in lines[i] and lines[i].strip():
                rows.append(split_row(lines[i]))
                i += 1
            width = max(len(r) for r in rows)
            rows = [r + [""] * (width - len(r)) for r in rows]
            blocks.append(("table", rows))
            continue

        if line.lstrip().startswith("> "):
            buf = []
            while i < n and lines[i].lstrip().startswith(">"):
                buf.append(lines[i].lstrip()[1:].strip())
                i += 1
            blocks.append(("quote", " ".join(x for x in buf if x)))
            continue

        m = ORDERED_RE.match(line)
        if m:
            level = min(len(m.group(1)) // 2, 1)
            buf = [m.group(3).strip()]
            i += 1
            while i < n and lines[i].strip() and not BULLET_RE.match(lines[i]) \
                    and not ORDERED_RE.match(lines[i]) \
                    and not HEAD_RE.match(lines[i]) and "|" not in lines[i] \
                    and not FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i].strip())
                i += 1
            blocks.append(("ordered", level, " ".join(buf)))
            continue

        m = BULLET_RE.match(line)
        if m:
            level = min(len(m.group(1)) // 2, 1)
            buf = [m.group(2).strip()]
            i += 1
            while i < n and lines[i].strip() and not BULLET_RE.match(lines[i]) \
                    and not ORDERED_RE.match(lines[i]) \
                    and not HEAD_RE.match(lines[i]) and "|" not in lines[i] \
                    and not FENCE_RE.match(lines[i].strip()):
                buf.append(lines[i].strip())
                i += 1
            blocks.append(("bullet", level, " ".join(buf)))
            continue

        buf = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not HEAD_RE.match(lines[i]) \
                and not BULLET_RE.match(lines[i]) \
                and not FENCE_RE.match(lines[i].strip()) \
                and not lines[i].lstrip().startswith(">") \
                and not ("|" in lines[i] and i + 1 < n and TABLE_SEP_RE.match(lines[i + 1])):
            buf.append(lines[i].strip())
            i += 1
        blocks.append(("p", " ".join(buf)))
    return blocks


# ------------------------------------------------------------------ inline ---

INLINE_RE = re.compile(
    r"(`[^`]+`"
    r"|\*\*[^*\n]+\*\*"
    r"|(?<![\w*])\*(?![\s*])[^*\n]+?(?<![\s*])\*(?![\w*]))"
)

TYPO_PUNCT = re.compile(r"(?<=\S)[  ]+([:;!?»])")


def typo_fr(text: str) -> str:
    """Applique la typographie francaise : apostrophe courbe, espace insecable."""
    text = text.replace("'", "’")
    text = TYPO_PUNCT.sub(" \\1", text)
    text = re.sub(r"«[  ]+", "« ", text)
    return text


def add_inline(paragraph, text: str, size_pt: float | None = None,
               typography: bool = True) -> None:
    for part in INLINE_RE.split(text):
        if not part:
            continue
        if part.startswith("`") and part.endswith("`") and len(part) > 2:
            run = paragraph.add_run(part[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(INLINE_CODE_PT if size_pt is None else size_pt - 0.5)
            run.font.color.rgb = RGBColor(0x1A, 0x1A, 0x1A)
            shd = OxmlElement("w:shd")
            shd.set(qn("w:val"), "clear")
            shd.set(qn("w:color"), "auto")
            shd.set(qn("w:fill"), "F0F0F0")
            run._element.get_or_add_rPr().append(shd)
        elif part.startswith("**") and part.endswith("**") and len(part) > 4:
            body = typo_fr(part[2:-2]) if typography else part[2:-2]
            run = paragraph.add_run(body)
            run.bold = True
            if size_pt:
                run.font.size = Pt(size_pt)
        elif part.startswith("*") and part.endswith("*") and len(part) > 2:
            body = typo_fr(part[1:-1]) if typography else part[1:-1]
            run = paragraph.add_run(body)
            run.italic = True
            if size_pt:
                run.font.size = Pt(size_pt)
        else:
            run = paragraph.add_run(typo_fr(part) if typography else part)
            if size_pt:
                run.font.size = Pt(size_pt)


# ------------------------------------------------------------------- styles ---

CODE_BLOC_XML = """<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 w:type="paragraph" w:customStyle="1" w:styleId="Codebloc">
<w:name w:val="Code bloc"/><w:next w:val="Normal"/><w:qFormat/>
<w:pPr><w:pBdr>
<w:top w:val="single" w:sz="4" w:space="6" w:color="000000"/>
<w:left w:val="single" w:sz="4" w:space="10" w:color="000000"/>
<w:bottom w:val="single" w:sz="4" w:space="6" w:color="000000"/>
<w:right w:val="single" w:sz="4" w:space="10" w:color="000000"/>
</w:pBdr><w:shd w:val="clear" w:color="auto" w:fill="000000"/>
<w:spacing w:before="120" w:after="160" w:line="240" w:lineRule="auto"/>
<w:ind w:left="142" w:right="0"/><w:contextualSpacing w:val="0"/><w:jc w:val="left"/></w:pPr>
<w:rPr><w:rFonts w:ascii="Consolas" w:hAnsi="Consolas" w:cs="Consolas"/><w:noProof/>
<w:color w:val="FFFFFF"/><w:kern w:val="0"/><w:sz w:val="16"/><w:szCs w:val="16"/></w:rPr>
</w:style>"""

CAPTION_XML = """<w:style xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
 w:type="paragraph" w:customStyle="1" w:styleId="Legende">
<w:name w:val="Legende"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/>
<w:pPr><w:spacing w:before="0" w:after="200"/><w:jc w:val="left"/></w:pPr>
<w:rPr><w:i/><w:color w:val="595959"/><w:sz w:val="18"/></w:rPr></w:style>"""


def ensure_styles(document) -> None:
    from docx.oxml import parse_xml

    styles = document.styles.element
    have = {s.get(qn("w:styleId")) for s in styles.findall(qn("w:style"))}
    for xml, sid in ((CODE_BLOC_XML, "Codebloc"), (CAPTION_XML, "Legende")):
        if sid not in have:
            styles.append(parse_xml(re.sub(r"\n\s*", " ", xml)))


# -------------------------------------------------------------- rendu blocs ---

def set_cell_shading(cell, fill: str) -> None:
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def add_list_item(document, level: int, text: str, num_id: int):
    p = document.add_paragraph(style="List Paragraph")
    numpr = OxmlElement("w:numPr")
    ilvl = OxmlElement("w:ilvl")
    ilvl.set(qn("w:val"), str(level))
    numid = OxmlElement("w:numId")
    numid.set(qn("w:val"), str(num_id))
    numpr.append(ilvl)
    numpr.append(numid)
    p._p.get_or_add_pPr().append(numpr)
    p.paragraph_format.space_after = Pt(2)
    add_inline(p, text)
    return p


def new_ordered_numid(document) -> int:
    """Cree une instance de numerotation decimale qui redemarre a 1."""
    from docx.oxml import parse_xml

    numbering = document.part.numbering_part.element
    used = {int(n.get(qn("w:numId"))) for n in numbering.findall(qn("w:num"))}
    num_id = max(used) + 1
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    numbering.append(parse_xml(
        f'<w:num {ns} w:numId="{num_id}">'
        f'<w:abstractNumId w:val="{ORDERED_ABSTRACT}"/>'
        f'<w:lvlOverride w:ilvl="0"><w:startOverride w:val="1"/></w:lvlOverride>'
        f'</w:num>'))
    return num_id


def code_font_size(lines: list[str]) -> float:
    """Reduit la police du bloc si une ligne depasse la largeur utile."""
    widest = max((len(line.replace("\t", "    ")) for line in lines), default=0)
    if widest <= 95:
        return CODE_PT
    if widest <= 110:
        return 7.0
    if widest <= 125:
        return 6.0
    return 5.5


def add_code(document, lines: list[str]):
    size = code_font_size(lines)
    p = document.add_paragraph(style="Codebloc")
    if len(lines) <= 24:
        p.paragraph_format.keep_together = True
    for idx, line in enumerate(lines):
        if idx:
            brk = p.add_run()
            brk.font.size = Pt(size)
            brk.add_break()
        run = p.add_run(line.replace("\t", "    "))
        run.font.name = "Consolas"
        run.font.size = Pt(size)
    return p


def add_diagram(document, name: str, caption: str):
    """Insere un diagramme SVG rasterise, dimensionne pour tenir dans la page."""
    from PIL import Image

    png = os.path.join(DIAGRAM_DIR, name + ".png")
    if not os.path.exists(png):
        png = diagram_lib.render(name, DIAGRAM_DIR)
    with Image.open(png) as img:
        pw, ph = img.size
    width = min(CONTENT_WIDTH_EMU, MAX_FIGURE_EMU * pw // ph)
    para = document.add_paragraph()
    para.alignment = WD_ALIGN_PARAGRAPH.CENTER
    para.paragraph_format.space_before = Pt(8)
    para.paragraph_format.space_after = Pt(2)
    para.paragraph_format.keep_together = True
    para.add_run().add_picture(png, width=Emu(width))
    if caption:
        cap = document.add_paragraph(style="Legende")
        cap.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_inline(cap, caption, size_pt=9.0)
    return para


def add_md_table(document, rows: list[list[str]]):
    ncols = len(rows[0])
    table = document.add_table(rows=len(rows), cols=ncols, style="Tableau bicolore")
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    tbl_pr = table._tbl.tblPr
    for tag in ("w:tblW", "w:tblLook"):
        for el in tbl_pr.findall(qn(tag)):
            tbl_pr.remove(el)
    w = OxmlElement("w:tblW")
    w.set(qn("w:w"), "5000")
    w.set(qn("w:type"), "pct")
    tbl_pr.append(w)
    look = OxmlElement("w:tblLook")
    look.set(qn("w:val"), "04A0")
    look.set(qn("w:firstRow"), "1")
    look.set(qn("w:lastRow"), "0")
    look.set(qn("w:firstColumn"), "0")
    look.set(qn("w:lastColumn"), "0")
    look.set(qn("w:noHBand"), "0")
    look.set(qn("w:noVBand"), "1")
    tbl_pr.append(look)

    for r, row in enumerate(rows):
        tr_pr = table.rows[r]._tr.get_or_add_trPr()
        cant = OxmlElement("w:cantSplit")
        tr_pr.append(cant)
        if r == 0:
            tr_pr.append(OxmlElement("w:tblHeader"))
        for c in range(ncols):
            cell = table.cell(r, c)
            para = cell.paragraphs[0]
            para.paragraph_format.space_after = Pt(0)
            para.alignment = WD_ALIGN_PARAGRAPH.LEFT
            if r == 0:
                para.style = document.styles["En-tête tableau"]
                set_cell_shading(cell, RED)
                add_inline(para, row[c], size_pt=9.0)
                for run in para.runs:
                    run.bold = True
                    run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
                    run.font.size = Pt(9)
            else:
                if r % 2 == 1:
                    set_cell_shading(cell, BAND)
                add_inline(para, row[c], size_pt=9.0)
                for run in para.runs:
                    if run.font.size is None:
                        run.font.size = Pt(9)
    return table


def render_body(document, blocks: list[tuple]) -> list[tuple[int, str, str]]:
    """Ecrit les blocs, pose les signets, retourne [(niveau, texte, ancre)]."""
    headings: list[tuple[int, str, str]] = []
    bm_id = 900000
    ordered_id = 0
    for block in blocks:
        kind = block[0]
        if kind != "ordered":
            ordered_id = 0
        if kind == "h":
            level, text = block[1], typo_fr(block[2])
            style = {1: "Heading 1", 2: "Heading 2", 3: "Heading 3", 4: "Heading 4"}[level]
            p = document.add_paragraph(style=style)
            if level == 1:
                p.paragraph_format.page_break_before = True
            anchor = f"_Toc{bm_id}"
            start = OxmlElement("w:bookmarkStart")
            start.set(qn("w:id"), str(bm_id))
            start.set(qn("w:name"), anchor)
            p._p.append(start)
            p.add_run(text)
            end = OxmlElement("w:bookmarkEnd")
            end.set(qn("w:id"), str(bm_id))
            p._p.append(end)
            headings.append((level, text, anchor))
            bm_id += 1
        elif kind == "p":
            p = document.add_paragraph()
            p.paragraph_format.space_after = Pt(8)
            add_inline(p, block[1])
        elif kind == "bullet":
            add_list_item(document, block[1], block[2], BULLET_NUMID)
        elif kind == "ordered":
            if not ordered_id:
                ordered_id = new_ordered_numid(document)
            add_list_item(document, block[1], block[2], ordered_id)
        elif kind == "code":
            add_code(document, block[2])
        elif kind == "diagram":
            add_diagram(document, block[1], block[2])
        elif kind == "table":
            add_md_table(document, block[1])
            spacer = document.add_paragraph()
            spacer.paragraph_format.space_after = Pt(6)
            for run in spacer.runs:
                run.font.size = Pt(4)
        elif kind == "quote":
            p = document.add_paragraph()
            p.paragraph_format.space_before = Pt(6)
            p.paragraph_format.space_after = Pt(10)
            p.paragraph_format.left_indent = Twips(284)
            pbdr = OxmlElement("w:pBdr")
            left = OxmlElement("w:left")
            left.set(qn("w:val"), "single")
            left.set(qn("w:sz"), "18")
            left.set(qn("w:space"), "8")
            left.set(qn("w:color"), RED)
            pbdr.append(left)
            p._p.get_or_add_pPr().append(pbdr)
            add_inline(p, block[1])
            for run in p.runs:
                run.italic = True
    return headings


# ---------------------------------------------------------------- sommaire ---

TOC_ENTRY = (
    '<w:p><w:pPr><w:pStyle w:val="TM{lvl}"/>'
    '<w:tabs><w:tab w:val="right" w:leader="dot" w:pos="9062"/></w:tabs>'
    '<w:rPr><w:noProof/></w:rPr></w:pPr>'
    '<w:hyperlink w:anchor="{anchor}" w:history="1">'
    '<w:r><w:rPr><w:rStyle w:val="Lienhypertexte"/><w:noProof/></w:rPr>'
    '<w:t xml:space="preserve">{text}</w:t></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:tab/></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr>'
    '<w:instrText xml:space="preserve"> PAGEREF {anchor} \\h </w:instrText></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:fldChar w:fldCharType="separate"/></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:t>{page}</w:t></w:r>'
    '<w:r><w:rPr><w:noProof/><w:webHidden/></w:rPr><w:fldChar w:fldCharType="end"/></w:r>'
    '</w:hyperlink></w:p>'
)

TOC_HEAD = (
    '<w:p><w:pPr><w:pStyle w:val="En-ttedetabledesmatires"/>'
    '<w:jc w:val="center"/></w:pPr><w:r><w:t>Sommaire</w:t></w:r></w:p>'
)

TOC_FIELD_BEGIN = (
    '<w:p><w:pPr><w:pStyle w:val="TM1"/><w:rPr><w:noProof/></w:rPr></w:pPr>'
    '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
    '<w:r><w:instrText xml:space="preserve"> TOC \\o "1-{depth}" \\h \\z \\u </w:instrText></w:r>'
    '<w:r><w:fldChar w:fldCharType="separate"/></w:r></w:p>'
)

TOC_FIELD_END = (
    '<w:p><w:pPr><w:rPr><w:b/><w:bCs/><w:noProof/><w:color w:val="ED1C24"/></w:rPr></w:pPr>'
    '<w:r><w:rPr><w:b/><w:bCs/><w:noProof/><w:color w:val="ED1C24"/></w:rPr>'
    '<w:fldChar w:fldCharType="end"/></w:r></w:p>'
)


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def build_toc_xml(headings, pages: dict[str, int], depth: int = 3) -> str:
    parts = [TOC_HEAD, TOC_FIELD_BEGIN.format(depth=depth)]
    for level, text, anchor in headings:
        if level > depth:
            continue
        parts.append(TOC_ENTRY.format(lvl=level, anchor=anchor, text=esc(text),
                                      page=pages.get(anchor, 0)))
    parts.append(TOC_FIELD_END)
    return "".join(parts)


def replace_toc(document, headings, pages, depth: int = 3) -> None:
    from docx.oxml import parse_xml

    body = document.element.body
    toc_sdt = None
    for sdt in body.findall(qn("w:sdt")):
        if sdt.findall(".//" + qn("w:docPartGallery")):
            gal = sdt.findall(".//" + qn("w:docPartGallery"))[0]
            if gal.get(qn("w:val")) == "Table of Contents":
                toc_sdt = sdt
                break
    if toc_sdt is None:
        raise RuntimeError("sdt de sommaire introuvable")
    content = toc_sdt.find(qn("w:sdtContent"))
    for child in list(content):
        content.remove(child)
    ns = ('xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
          'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"')
    wrapped = parse_xml(
        f"<w:root {ns}>{build_toc_xml(headings, pages, depth)}</w:root>")
    for child in list(wrapped):
        content.append(child)


# ----------------------------------------------------------------- montage ---

def clear_after_toc(document) -> None:
    body = document.element.body
    children = list(body)
    idx = None
    for i, child in enumerate(children):
        if child.tag == qn("w:sdt") and child.findall(".//" + qn("w:docPartGallery")):
            gal = child.findall(".//" + qn("w:docPartGallery"))[0]
            if gal.get(qn("w:val")) == "Table of Contents":
                idx = i
    if idx is None:
        raise RuntimeError("sdt de sommaire introuvable")
    for child in children[idx + 1:]:
        if child.tag != qn("w:sectPr"):
            body.remove(child)


def set_cell_text(cell, text: str, bold: bool = False) -> None:
    cell.text = ""
    para = cell.paragraphs[0]
    para.paragraph_format.space_after = Pt(0)
    run = para.add_run(text)
    run.bold = bold


def fill_front_tables(document, meta: dict) -> None:
    validation, revisions = document.tables[0], document.tables[1]
    set_cell_text(validation.cell(0, 1), meta["owner"])
    set_cell_text(validation.cell(1, 1), meta["author"])
    set_cell_text(validation.cell(1, 3), meta["date"])
    set_cell_text(validation.cell(2, 1), "")
    set_cell_text(validation.cell(2, 3), "")
    set_cell_text(validation.cell(3, 1), "")
    set_cell_text(validation.cell(3, 3), "")
    set_cell_text(revisions.cell(1, 0), meta["version"])
    set_cell_text(revisions.cell(1, 1), meta["date"])
    set_cell_text(revisions.cell(1, 2), meta["changelog"])
    set_cell_text(revisions.cell(1, 3), meta["author"])


TEXT_SUBS = {
    "word/document.xml": [("TITRE", "cover_title"), ("Sous-titre", "cover_subtitle"),
                          ("Version 1.0", "version_label")],
}

DATA_BINDING_RE = re.compile(r"<w:dataBinding[^>]*/>")
TLP_FILES = ("word/document.xml", "word/footer1.xml")


def patch_zip_texts(path: str, meta: dict) -> None:
    """Remplace les textes de la page de garde, de l'en-tete, du pied et des proprietes."""
    tmp = path + ".tmp"
    with zipfile.ZipFile(path) as zin, zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename in TEXT_SUBS or item.filename in TLP_FILES:
                xml = data.decode("utf-8")
                if item.filename in TEXT_SUBS:
                    xml = DATA_BINDING_RE.sub("", xml)
                    for literal, key in TEXT_SUBS[item.filename]:
                        xml = re.sub(r"(<w:t(?: [^>]*)?>)%s(</w:t>)" % re.escape(literal),
                                     lambda m, v=esc(meta[key]): m.group(1) + v + m.group(2), xml)
                if item.filename in TLP_FILES:
                    xml, _ = cover.strip_marker_shapes(xml, "TLP")
                data = xml.encode("utf-8")
            elif item.filename == "docProps/core.xml":
                xml = data.decode("utf-8")
                xml = re.sub(r"<dc:title>.*?</dc:title>",
                             "<dc:title>%s</dc:title>" % esc(meta["prop_title"]), xml)
                xml = re.sub(r"<dc:subject>.*?</dc:subject>",
                             "<dc:subject>%s</dc:subject>" % esc(meta["header_right"]), xml)
                xml = re.sub(r"<dc:creator>.*?</dc:creator>",
                             "<dc:creator>%s</dc:creator>" % esc(meta["author"]), xml)
                xml = re.sub(r"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>",
                             "<cp:lastModifiedBy>%s</cp:lastModifiedBy>" % esc(meta["author"]), xml)
                xml = re.sub(r"<cp:keywords>.*?</cp:keywords>",
                             "<cp:keywords>%s</cp:keywords>" % esc(meta.get("keywords", "")), xml)
                xml = re.sub(r"<dc:description>.*?</dc:description>",
                             "<dc:description>%s</dc:description>"
                             % esc(meta.get("cover_subtitle", "")), xml)
                data = xml.encode("utf-8")
            zout.writestr(item, data)
    os.replace(tmp, path)


def build_docx(template: str, out_path: str, meta: dict, blocks: list[tuple],
               pages: dict[str, int], toc_depth: int = 3) -> list[tuple[int, str, str]]:
    shutil.copyfile(template, out_path)
    document = docx.Document(out_path)
    ensure_styles(document)
    clear_after_toc(document)
    fill_front_tables(document, meta)
    headings = render_body(document, blocks)
    replace_toc(document, headings, pages, toc_depth)
    document.save(out_path)
    patch_zip_texts(out_path, meta)
    cover.patch_cover(out_path)
    return headings


def to_pdf(docx_path: str, outdir: str) -> str:
    subprocess.run([SOFFICE, "--headless", "--norestore", "--convert-to", "pdf",
                    "--outdir", outdir, docx_path], check=True,
                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    pdf = os.path.join(outdir, os.path.splitext(os.path.basename(docx_path))[0] + ".pdf")
    if not os.path.exists(pdf):
        raise RuntimeError("conversion PDF echouee : " + pdf)
    return pdf


def outline_pages(pdf_path: str, headings) -> dict[str, int]:
    """Numero de page imprime (PAGE field) pour chaque signet, via le plan du PDF."""
    import fitz

    doc = fitz.open(pdf_path)
    toc = doc.get_toc()
    doc.close()
    if len(toc) != len(headings):
        raise RuntimeError(f"plan PDF ({len(toc)}) != titres ({len(headings)})")
    return {h[2]: max(t[2] - 1, 1) for h, t in zip(headings, toc)}


def build_pdf(template: str, workdir: str, name: str, meta: dict, md_text: str,
              toc_depth: int = 3) -> str:
    blocks = parse_md(md_text)
    docx_path = os.path.join(workdir, name + ".docx")
    headings = build_docx(template, docx_path, meta, blocks, {}, toc_depth)
    pdf = to_pdf(docx_path, workdir)
    for _ in range(3):
        pages = outline_pages(pdf, headings)
        build_docx(template, docx_path, meta, blocks, pages, toc_depth)
        pdf = to_pdf(docx_path, workdir)
        if outline_pages(pdf, headings) == pages:
            break
    return pdf


if __name__ == "__main__":
    print("module", __file__)
