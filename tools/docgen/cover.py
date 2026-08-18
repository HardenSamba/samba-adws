"""Compose le degrade de couverture dans l'image de fond (LibreOffice n'affiche pas la forme)."""

from __future__ import annotations

import io
import re
import zipfile

import numpy as np
from PIL import Image

# Geometrie relevee dans word/document.xml du template (EMU).
IMG_X0, IMG_Y0 = -398780, -811530
IMG_CX, IMG_CY = 8458200, 11519137
RECT_X0, RECT_Y0 = -57150, -819150
RECT_L = 11585575

STOP_A = (0.01, np.array([0xED, 0x1C, 0x24], dtype=np.float64), 1.00)
STOP_B = (1.00, np.array([0x00, 0x00, 0x00], dtype=np.float64), 0.60)


def gradient_overlay(width: int, height: int) -> tuple[np.ndarray, np.ndarray]:
    """Renvoie (couleur RGB, alpha) du degrade lineaire 45 degres pour chaque pixel."""
    xs = IMG_X0 + (np.arange(width) + 0.5) * (IMG_CX / width) - RECT_X0
    ys = IMG_Y0 + (np.arange(height) + 0.5) * (IMG_CY / height) - RECT_Y0
    t = (xs[None, :] + ys[:, None]) / (2.0 * RECT_L)
    p0, c0, a0 = STOP_A
    p1, c1, a1 = STOP_B
    f = np.clip((t - p0) / (p1 - p0), 0.0, 1.0)[..., None]
    color = c0[None, None, :] * (1.0 - f) + c1[None, None, :] * f
    alpha = a0 + (a1 - a0) * f[..., 0]
    return color, alpha


def compose_cover(photo_bytes: bytes) -> bytes:
    photo = Image.open(io.BytesIO(photo_bytes)).convert("RGB")
    base = np.asarray(photo, dtype=np.float64)
    height, width = base.shape[:2]
    color, alpha = gradient_overlay(width, height)
    out = base * (1.0 - alpha[..., None]) + color * alpha[..., None]
    buf = io.BytesIO()
    Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)).save(buf, "JPEG", quality=88)
    return buf.getvalue()


RECT_RUN = re.compile(
    r'<w:r(?: [^>]*)?>(?:(?!</w:r>).)*?name="Rectangle 3".*?</w:r>', re.S)

RUN_OPEN = re.compile(r"<w:r(?: [^>]*)?>")


# Supprime les blocs graphiques dont le contenu porte le marqueur donne.
def strip_marker_shapes(xml: str, marker: str) -> tuple[str, int]:
    removed = 0
    while True:
        spans = _alternate_content_spans(xml)
        target = next((s for s in spans if marker in xml[s[0]:s[1]]), None)
        if target is None:
            return xml, removed
        start = _enclosing_run_start(xml, target[0])
        end = xml.find("</w:r>", target[1])
        if start is None or end == -1:
            return xml, removed
        xml = xml[:start] + xml[end + len("</w:r>"):]
        removed += 1


# Renvoie les bornes de chaque bloc mc:AlternateContent de premier niveau.
def _alternate_content_spans(xml: str) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    token = re.compile(r"<mc:AlternateContent[ >]|</mc:AlternateContent>")
    depth, start = 0, 0
    for match in token.finditer(xml):
        if match.group().startswith("</"):
            depth -= 1
            if depth == 0:
                spans.append((start, match.end()))
        else:
            if depth == 0:
                start = match.start()
            depth += 1
    return spans


# Position d'ouverture du <w:r> qui contient la position donnee.
def _enclosing_run_start(xml: str, position: int) -> int | None:
    last = None
    for match in RUN_OPEN.finditer(xml, 0, position):
        last = match.start()
    return last


def patch_cover(path: str) -> None:
    """Cuit le degrade dans media/image4.jpeg et retire la forme devenue redondante."""
    tmp = path + ".cover"
    with zipfile.ZipFile(path) as zin:
        names = zin.namelist()
        photo = zin.read("word/media/image4.jpeg")
        baked = compose_cover(photo)
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zout:
            for item in zin.infolist():
                if item.filename == "word/media/image4.jpeg":
                    zout.writestr(item.filename, baked)
                    continue
                data = zin.read(item.filename)
                if item.filename == "word/document.xml":
                    xml = data.decode("utf-8")
                    xml, count = RECT_RUN.subn("", xml, count=1)
                    if count != 1:
                        raise RuntimeError("forme Rectangle 3 introuvable dans la couverture")
                    data = xml.encode("utf-8")
                zout.writestr(item, data)
    assert names
    import os
    os.replace(tmp, path)
