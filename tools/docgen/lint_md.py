"""Verifie que les chapitres respectent le contrat de format avant assemblage."""

from __future__ import annotations

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import docgen  # noqa: E402

MAX_CODE = 95
LINK_RE = re.compile(r"\[[^\]]+\]\([^)]+\)")
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF☀-⛿️]")


def check(path: str) -> list[str]:
    problems: list[str] = []
    text = open(path, encoding="utf-8").read()
    lines = text.split("\n")
    in_code = False
    fence_lang = ""
    for no, line in enumerate(lines, start=1):
        m_fence = docgen.FENCE_RE.match(line.strip())
        if m_fence:
            if not in_code:
                fence_lang = m_fence.group(1)
            in_code = not in_code
            continue
        if in_code:
            if not fence_lang.startswith("schema:") and \
                    len(line.replace("\t", "    ")) > MAX_CODE:
                problems.append(f"{no}: bloc de code {len(line)} car. > {MAX_CODE}")
            continue
        m = docgen.HEAD_RE.match(line)
        if line.startswith("#") and not m:
            problems.append(f"{no}: titre de niveau > 4 ou mal forme : {line[:60]!r}")
        if LINK_RE.search(line):
            problems.append(f"{no}: lien Markdown interdit : {LINK_RE.search(line).group()[:50]!r}")
        if EMOJI_RE.search(line):
            problems.append(f"{no}: emoji")
    if in_code:
        problems.append("bloc de code non ferme en fin de fichier")

    blocks = docgen.parse_md(text)
    for kind, *rest in blocks:
        if kind == "table":
            rows = rest[0]
            width = len(rows[0])
            if width > 5:
                problems.append(f"tableau a {width} colonnes (max 5) : {rows[0]}")
            for row in rows:
                if len(row) != width:
                    problems.append(f"tableau irregulier : {row}")
    stats = {
        "titres": sum(1 for b in blocks if b[0] == "h"),
        "tableaux": sum(1 for b in blocks if b[0] == "table"),
        "blocs_code": sum(1 for b in blocks if b[0] == "code"),
        "puces": sum(1 for b in blocks if b[0] == "bullet"),
        "paragraphes": sum(1 for b in blocks if b[0] == "p"),
        "mots": len(text.split()),
    }
    print(f"  {path.rsplit(os.sep, 1)[-1]:<24} " +
          "  ".join(f"{k}={v}" for k, v in stats.items()))
    return problems


def main() -> int:
    folder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chapters")
    total = 0
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".md"):
            continue
        problems = check(os.path.join(folder, name))
        total += len(problems)
        for problem in problems[:40]:
            print(f"      ! {problem}")
        if len(problems) > 40:
            print(f"      ... et {len(problems) - 40} autres")
    print(f"\n{total} anomalie(s) de format")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
