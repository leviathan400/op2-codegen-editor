"""Einmal-Skript: zerlegt main.py mechanisch in das Paket app/ (verbatim).

Schneidet an den bekannten Klassengrenzen, setzt pro Modul die noetigen
Importe. main.py bleibt unangetastet.
"""
from pathlib import Path

HERE = Path(__file__).resolve().parent
lines = (HERE / "main.py").read_text(encoding="utf-8").splitlines(keepends=True)


def slice_(a, b):  # 1-indexierte, inklusive Zeilenbereiche
    return "".join(lines[a - 1:b])


app = HERE / "app"
(app / "dialogs").mkdir(parents=True, exist_ok=True)

# --- common.py: gemeinsamer Header + Konstanten + Summaries ---
common_header = '''from __future__ import annotations

import json
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent      # editor/app
EDITOR_DIR = HERE.parent                      # editor
ROOT = EDITOR_DIR.parent                       # op2-cpp-poc
for _p in (ROOT / "codegen", ROOT / "mapview", EDITOR_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

'''
common_body = slice_(24, 259).replace(
    'CONFIG_PATH = HERE / "config.json"',
    'CONFIG_PATH = EDITOR_DIR / "config.json"',
)
(app / "common.py").write_text(common_header + common_body, encoding="utf-8")

# --- Module im Paket-Root ---
def write_mod(name, a, b, extra_imports=""):
    head = "from __future__ import annotations\nfrom .common import *\n" + extra_imports + "\n\n"
    (app / f"{name}.py").write_text(head + slice_(a, b), encoding="utf-8")

write_mod("placed_object", 261, 292)
write_mod("mapview", 293, 361)
write_mod("build_worker", 1743, 1760)

# --- Dialoge (parent-Paket-Import: ..common) ---
def write_dlg(name, a, b, extra_imports=""):
    head = "from __future__ import annotations\nfrom ..common import *\n" + extra_imports + "\n\n"
    (app / "dialogs" / f"{name}.py").write_text(head + slice_(a, b), encoding="utf-8")

write_dlg("map_dialog", 362, 384)
write_dlg("object_edit", 385, 444, "from ..placed_object import PlacedObject\n")
write_dlg("output_dialog", 445, 475)
write_dlg("conditions", 476, 577)
write_dlg("players", 578, 785)
write_dlg("triggers", 786, 1397)
write_dlg("groups", 1398, 1742)

# --- window.py: Fenster + alle Klassen-Importe ---
window_head = (
    "from __future__ import annotations\n"
    "from .common import *\n"
    "from .placed_object import PlacedObject\n"
    "from .mapview import MapView\n"
    "from .build_worker import BuildWorker\n"
    "from .dialogs.map_dialog import MapDialog\n"
    "from .dialogs.object_edit import ObjectEditDialog\n"
    "from .dialogs.output_dialog import OutputDialog\n"
    "from .dialogs.conditions import ConditionsDialog\n"
    "from .dialogs.players import PlayersDialog\n"
    "from .dialogs.triggers import TriggersDialog\n"
    "from .dialogs.groups import GroupsDialog\n\n\n"
)
(app / "window.py").write_text(window_head + slice_(1761, 2775), encoding="utf-8")

# --- __main__.py: Einstieg ---
main_body = slice_(2776, 2784)
(app / "__main__.py").write_text(
    "from __future__ import annotations\n"
    "import sys\n"
    "from .common import QApplication\n"
    "from .window import EditorWindow\n\n\n" + main_body
    + '\n\nif __name__ == "__main__":\n    main()\n',
    encoding="utf-8",
)

# --- __init__.py ---
(app / "__init__.py").write_text('"""Modularer OP2 Mission Editor (Kopie von main.py)."""\n', encoding="utf-8")
(app / "dialogs" / "__init__.py").write_text("", encoding="utf-8")

print("Split fertig. Module:")
for f in sorted(app.rglob("*.py")):
    print(f"  {f.relative_to(HERE)}  ({len(f.read_text(encoding='utf-8').splitlines())} Zeilen)")
