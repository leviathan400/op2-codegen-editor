"""Liest die OP2-Technologie-Datei (z.B. multitek.txt) -> Liste (techID, Name).

Format je Tech:  BEGIN_TECH "Name" 03401  ... END_TECH
SetTechLevel(N) vergibt automatisch alle Techs mit techID <= N*1000.
"""
from __future__ import annotations

import re
from pathlib import Path

_PATTERN = re.compile(r'BEGIN_TECH\s+"([^"]+)"\s+(\d+)')


def load_techs(path: str | Path) -> list[tuple[int, str]]:
    """Gibt eine nach ID sortierte Liste von (techID, Name) zurueck."""
    try:
        text = Path(path).read_text(encoding="latin-1", errors="replace")
    except Exception:
        return []
    techs = [(int(tid), name) for name, tid in _PATTERN.findall(text)]
    techs.sort(key=lambda t: t[0])
    return techs


if __name__ == "__main__":
    import sys
    techs = load_techs(sys.argv[1])
    print(f"{len(techs)} Technologien")
    for tid, name in techs[:15]:
        print(f"  {tid:>5}  {name}")
