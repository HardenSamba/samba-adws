"""Assemble le document unique de documentation ADWS."""

from __future__ import annotations

import os
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import diagrams  # noqa: E402
import docgen  # noqa: E402
import merge  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TEMPLATE = os.path.join(REPO, "documentation", "templateDocumentation.docx")
WORK = os.path.join(HERE, "build")
DEST = os.path.join(REPO, "documentation", "pdf")
DEST_DOCX = os.path.join(REPO, "documentation", "word")

AUTHOR = "Martin PETIT"
OWNER = "SYNETIS"
DATE = "13/08/2026"
VERSION = "1.0"
CHANGELOG = "Création du document"
NAME = "ADWS-documentation"

META = {
    "cover_title": "DOCUMENTATION ADWS",
    "cover_subtitle": "Active Directory Web Services : protocoles, échanges "
                      "et mise en œuvre",
    "version_label": f"Version {VERSION}",
    "header_right": f"Version {VERSION}",
    "prop_title": "Active Directory Web Services : protocoles et mise en œuvre",
    "version": VERSION,
    "author": AUTHOR,
    "owner": OWNER,
    "date": DATE,
    "changelog": CHANGELOG,
    "keywords": "ADWS, Active Directory, Samba, Kerberos, SOAP, WS-Transfer",
}


UPDATE_FIELDS = '<w:updateFields w:val="true"/>'


# Copie le DOCX en demandant a Word de recalculer sommaire et pagination.
def export_docx(source: str, target: str) -> None:
    import zipfile

    os.makedirs(os.path.dirname(target), exist_ok=True)
    with zipfile.ZipFile(source) as zin, \
            zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zout:
        for item in zin.infolist():
            data = zin.read(item.filename)
            if item.filename == "word/settings.xml":
                xml = data.decode("utf-8")
                if "updateFields" not in xml:
                    xml = xml.replace("<w:defaultTabStop",
                                      UPDATE_FIELDS + "<w:defaultTabStop", 1)
                data = xml.encode("utf-8")
            zout.writestr(item, data)


# Produit le document unique, du Markdown fusionne au PDF final.
def main() -> int:
    os.makedirs(WORK, exist_ok=True)
    os.makedirs(DEST, exist_ok=True)
    diagrams.render_all(os.path.join(WORK, "diagrams"))
    print(f"[OK] {len(diagrams.REGISTRY)} diagrammes")
    markdown = merge.build()
    source = os.path.join(HERE, "chapters", "complete.md")
    with open(source, "w", encoding="utf-8") as handle:
        handle.write(markdown)
    pdf = docgen.build_pdf(TEMPLATE, WORK, NAME, META, markdown, toc_depth=2)
    target = os.path.join(DEST, NAME + ".pdf")
    shutil.copyfile(pdf, target)
    word = os.path.join(DEST_DOCX, NAME + ".docx")
    export_docx(os.path.join(WORK, NAME + ".docx"), word)
    import fitz

    doc = fitz.open(target)
    print(f"[OK] {target}")
    print(f"     {len(doc)} pages, {len(markdown.split())} mots, "
          f"{len(doc.get_toc())} entrees de plan")
    doc.close()
    print(f"[OK] {word}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
