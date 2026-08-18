"""Primitives SVG et moteur de diagrammes pour la documentation ADWS (charte SYNETIS)."""

from __future__ import annotations

from dataclasses import dataclass, field

INK = "#1A1A1A"
RED = "#ED1C24"
GREY = "#6B6B6B"
LIFE = "#B9B9B9"
FILL = "#F4F4F4"
NOTE = "#FCEBD6"
NOTE_BD = "#E0A96A"
BAND = "#FBE2E3"
SANS = "Trebuchet MS, Verdana, sans-serif"
MONO = "Consolas, monospace"

CHAR_SANS = 0.53
CHAR_MONO = 0.55


def esc(text: str) -> str:
    return (text.replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def text_width(text: str, size: float, mono: bool = False) -> float:
    return len(text) * size * (CHAR_MONO if mono else CHAR_SANS)


# ------------------------------------------------------------------ atomes ---

def svg_text(x: float, y: float, s: str, size: float = 26, color: str = INK,
             anchor: str = "start", mono: bool = False, bold: bool = False) -> str:
    family = MONO if mono else SANS
    weight = ' font-weight="700"' if bold else ""
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-family="{family}" '
            f'font-size="{size:.1f}" fill="{color}" text-anchor="{anchor}"'
            f'{weight}>{esc(s)}</text>')


def rect(x: float, y: float, w: float, h: float, fill: str, stroke: str = "none",
         rx: float = 0, sw: float = 2) -> str:
    st = f' stroke="{stroke}" stroke-width="{sw}"' if stroke != "none" else ""
    return (f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" '
            f'rx="{rx}" fill="{fill}"{st}/>')


def line(x1: float, y1: float, x2: float, y2: float, color: str = INK,
         sw: float = 2, dash: str | None = None) -> str:
    da = f' stroke-dasharray="{dash}"' if dash else ""
    return (f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
            f'stroke="{color}" stroke-width="{sw}"{da}/>')


def arrowhead(x: float, y: float, direction: int, color: str, size: float = 12) -> str:
    dx = size * direction
    return (f'<path d="M {x:.1f} {y:.1f} L {x - dx:.1f} {y - size * 0.6:.1f} '
            f'L {x - dx:.1f} {y + size * 0.6:.1f} Z" fill="{color}"/>')


def arrowhead_down(x: float, y: float, color: str, size: float = 12) -> str:
    return (f'<path d="M {x:.1f} {y:.1f} L {x - size * 0.6:.1f} {y - size:.1f} '
            f'L {x + size * 0.6:.1f} {y - size:.1f} Z" fill="{color}"/>')


def document(width: float, height: float, body: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{width:.0f}" '
            f'height="{height:.0f}" viewBox="0 0 {width:.0f} {height:.0f}">'
            f'<rect width="{width:.0f}" height="{height:.0f}" fill="#FFFFFF"/>'
            f'{body}</svg>')


# ----------------------------------------------------- diagramme de sequence ---

@dataclass
class _Event:
    kind: str
    data: dict = field(default_factory=dict)
    height: float = 0.0


@dataclass
class Sequence:
    """Moteur de diagramme de sequence : acteurs, messages, notes, dividers, gouttiere."""

    actors: list[tuple[str, str, str]]
    gutter: bool = True
    width: float = 1720.0
    title: str = ""
    show_anchors: bool = True

    def __post_init__(self) -> None:
        self._events: list[_Event] = []
        self._index = {a[0]: i for i, a in enumerate(self.actors)}

    def divider(self, text: str) -> None:
        self._events.append(_Event("divider", {"text": text}, 66))

    def msg(self, src: str, dst: str, text: str, kind: str = "req",
            anchor: str = "") -> None:
        lines = text.split("\n")
        self._events.append(_Event(
            "msg", {"src": src, "dst": dst, "lines": lines, "kind": kind,
                    "anchor": anchor}, 34 + len(lines) * 30 + 26))

    def selfmsg(self, actor: str, text: str, anchor: str = "") -> None:
        lines = text.split("\n")
        self._events.append(_Event(
            "self", {"actor": actor, "lines": lines, "anchor": anchor},
            30 + len(lines) * 30 + 20))

    def note(self, actor: str, text: str, side: str = "auto") -> None:
        lines = text.split("\n")
        self._events.append(_Event(
            "note", {"actor": actor, "lines": lines, "side": side},
            26 + len(lines) * 30 + 22))

    def gap(self, height: float = 26) -> None:
        self._events.append(_Event("gap", {}, height))

    # -- geometrie ---------------------------------------------------------

    def _columns(self) -> dict[str, float]:
        left = 60.0
        right = self.width - (360.0 if self.gutter else 60.0)
        n = len(self.actors)
        span = right - left
        return {a[0]: left + span * (i + 0.5) / n for i, a in enumerate(self.actors)}

    def _actor_header(self, cols: dict[str, float], top: float) -> str:
        out = []
        box_h = 84.0
        for aid, name, sub in self.actors:
            cx = cols[aid]
            label_w = max(text_width(name, 27, ), text_width(sub, 22)) + 60
            bw = max(300.0, label_w)
            out.append(rect(cx - bw / 2, top, bw, box_h, RED, rx=10))
            out.append(svg_text(cx, top + 34, name, 27, "#FFFFFF", "middle", bold=True))
            if sub:
                out.append(svg_text(cx, top + 64, sub, 21, "#FFECEC", "middle"))
        return "".join(out), box_h

    def _render_msg(self, ev: _Event, cols: dict[str, float], y: float) -> str:
        d = ev.data
        x1, x2 = cols[d["src"]], cols[d["dst"]]
        out = []
        base = y + ev.height - 20
        top = y + 8
        for i, ln in enumerate(d["lines"]):
            mid = (x1 + x2) / 2
            out.append(svg_text(mid, top + 24 + i * 30, ln, 24, INK, "middle"))
        direction = 1 if x2 >= x1 else -1
        color = INK if d["kind"] == "req" else GREY
        dash = None if d["kind"] == "req" else "10,7"
        out.append(line(x1, base, x2 - direction * 6, base, color, 2.4, dash))
        out.append(arrowhead(x2, base, direction, color))
        if d["anchor"] and self.show_anchors:
            out.append(svg_text(self.width - 340, base + 6, d["anchor"], 22,
                                 GREY, "start", mono=True))
        return "".join(out)

    def _render_self(self, ev: _Event, cols: dict[str, float], y: float) -> str:
        d = ev.data
        x = cols[d["actor"]]
        idx = self._index[d["actor"]]
        out = []
        top = y + 6
        w = max((text_width(ln, 23) for ln in d["lines"]), default=120) + 46
        left_side = idx == len(self.actors) - 1
        bx = x - 26 - w if left_side else x + 26
        out.append(rect(bx, top, w, ev.height - 16, FILL, LIFE, rx=8, sw=1.6))
        for i, ln in enumerate(d["lines"]):
            out.append(svg_text(bx + 22, top + 32 + i * 30, ln, 23, INK))
        loop = y + ev.height - 24
        hook = -1 if left_side else 1
        out.append(line(x, loop - 16, x + 24 * hook, loop - 16, RED, 2.2))
        out.append(line(x + 24 * hook, loop - 16, x + 24 * hook, loop, RED, 2.2))
        out.append(line(x + 24 * hook, loop, x + 6 * hook, loop, RED, 2.2))
        out.append(arrowhead(x, loop, hook, RED, 10))
        if d["anchor"] and self.show_anchors:
            out.append(svg_text(self.width - 340, loop + 4, d["anchor"], 22,
                                 GREY, "start", mono=True))
        return "".join(out)

    def _render_note(self, ev: _Event, cols: dict[str, float], y: float) -> str:
        d = ev.data
        x = cols[d["actor"]]
        idx = self._index[d["actor"]]
        side = d["side"]
        if side == "auto":
            side = "left" if idx == len(self.actors) - 1 else "right"
        w = max((text_width(ln, 23) for ln in d["lines"]), default=120) + 46
        bx = x + 30 if side == "right" else x - 30 - w
        out = [rect(bx, y + 6, w, ev.height - 14, NOTE, NOTE_BD, rx=8, sw=1.6)]
        for i, ln in enumerate(d["lines"]):
            out.append(svg_text(bx + 23, y + 34 + i * 30, ln, 23, INK))
        return "".join(out)

    def to_svg(self) -> str:
        cols = self._columns()
        top = 24.0 + (48 if self.title else 0)
        header, box_h = self._actor_header(cols, top)
        y0 = top + box_h + 18
        y = y0
        body = []
        for ev in self._events:
            if ev.kind == "divider":
                body.append(rect(30, y + 12, self.width - 60, ev.height - 22, BAND, rx=8))
                body.append(svg_text(self.width / 2, y + ev.height / 2 + 4,
                                      ev.data["text"], 25, RED, "middle", bold=True))
            elif ev.kind == "msg":
                body.append(self._render_msg(ev, cols, y))
            elif ev.kind == "self":
                body.append(self._render_self(ev, cols, y))
            elif ev.kind == "note":
                body.append(self._render_note(ev, cols, y))
            y += ev.height
        bottom = y + 12
        lifelines = [line(cols[a[0]], y0, cols[a[0]], bottom, LIFE, 2, "3,7")
                     for a in self.actors]
        gutter = ""
        if self.gutter and self.show_anchors:
            gx = self.width - 348
            gutter = (line(gx, y0, gx, bottom, "#E4E4E4", 1.5) +
                      svg_text(gx + 6, y0 - 6, "code source", 20, GREY, "start", mono=True))
        title = ""
        if self.title:
            title = svg_text(self.width / 2, 40, self.title, 30, INK, "middle", bold=True)
        return document(self.width, bottom + 20,
                        title + "".join(lifelines) + gutter + header + "".join(body))


# --------------------------------------------------------- pile en couches ---

def stack(layers: list[tuple[str, str]], width: float = 1500,
          note_col: bool = True) -> str:
    """Diagramme d'empilement : liste (contenu, annotation) de haut en bas."""
    row_h = 92.0
    pad = 24.0
    lx, lw = pad, (width - 3 * pad) * (0.66 if note_col else 1.0)
    nx = lx + lw + pad
    body = []
    for i, (content, note) in enumerate(layers):
        y = pad + i * (row_h + 12)
        shade = "#2A2A2A" if i % 2 == 0 else "#1A1A1A"
        body.append(rect(lx, y, lw, row_h, shade, RED, rx=10, sw=1.6))
        body.append(svg_text(lx + 30, y + row_h / 2 + 9, content, 26, "#FFFFFF"))
        if note_col and note:
            body.append(svg_text(nx, y + row_h / 2 + 8, note, 23, RED, "start", mono=True))
    height = pad + len(layers) * (row_h + 12)
    for i in range(len(layers) - 1):
        y = pad + i * (row_h + 12) + row_h + 6
        cx = lx + lw / 2
        body.append(line(cx, y - 4, cx, y + 8, GREY, 2))
    return document(width, height, "".join(body))


# ------------------------------------------------------ flot / pipeline -----

@dataclass
class Flow:
    """Enchainement horizontal ou vertical de boites reliees par des fleches."""

    steps: list[tuple[str, str]]
    width: float = 1680.0
    vertical: bool = False
    accent_last: bool = False

    def to_svg(self) -> str:
        return self._vertical() if self.vertical else self._horizontal()

    def _box(self, x: float, y: float, w: float, h: float, title: str,
             sub: str, accent: bool) -> str:
        fill = RED if accent else FILL
        stroke = RED if not accent else "none"
        tcol = "#FFFFFF" if accent else INK
        scol = "#FFECEC" if accent else GREY
        out = [rect(x, y, w, h, fill, stroke, rx=12, sw=2)]
        out.append(svg_text(x + w / 2, y + (h / 2 - 4 if sub else h / 2 + 8),
                            title, 25, tcol, "middle", bold=True))
        if sub:
            out.append(svg_text(x + w / 2, y + h / 2 + 26, sub, 20, scol,
                                "middle", mono=True))
        return "".join(out)

    def _horizontal(self) -> str:
        n = len(self.steps)
        gap = 46.0
        h = 120.0
        w = (self.width - 60 - gap * (n - 1)) / n
        y = 30.0
        body = []
        for i, (title, sub) in enumerate(self.steps):
            x = 30 + i * (w + gap)
            accent = self.accent_last and i == n - 1
            body.append(self._box(x, y, w, h, title, sub, accent))
            if i < n - 1:
                ax = x + w
                body.append(line(ax + 6, y + h / 2, ax + gap - 12, y + h / 2, RED, 3))
                body.append(arrowhead(ax + gap - 6, y + h / 2, 1, RED, 12))
        return document(self.width, y + h + 30, "".join(body))

    def _vertical(self) -> str:
        n = len(self.steps)
        gap = 40.0
        h = 104.0
        w = self.width - 120
        x = 60.0
        body = []
        for i, (title, sub) in enumerate(self.steps):
            y = 30 + i * (h + gap)
            accent = self.accent_last and i == n - 1
            body.append(self._box(x, y, w, h, title, sub, accent))
            if i < n - 1:
                ay = y + h
                body.append(line(x + w / 2, ay + 6, x + w / 2, ay + gap - 10, RED, 3))
                body.append(arrowhead_down(x + w / 2, ay + gap - 2, RED, 13))
        return document(self.width, 30 + n * (h + gap), "".join(body))
