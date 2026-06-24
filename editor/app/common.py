from __future__ import annotations

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

from PySide6.QtCore import Qt, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QFormLayout, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressDialog, QPushButton, QSpinBox, QTabWidget, QToolBar, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
    QGraphicsItem, QGraphicsPathItem, QGraphicsEllipseItem, QMenu, QFrame, QScrollArea,
)
from PySide6.QtGui import QFont, QPainterPath, QPolygonF, QCursor
from PySide6.QtCore import QPointF

from op2map import Op2Map
from render import render_array
from tileset import TILE
from vol import VolFile

import build as build_mod
from codegen import generate_levelmain
from mission_model import (
    ActionCondition, BeaconSpec, BuildingGroupSpec, Colony, Condition, MiningGroupSpec,
    Mission, MissionType, PlayerSpec, ReinforceGroupSpec, ReinforceTargetSpec,
    StartMessage, TriggerAction, TriggerDef, UnitSpec, WallTubeSpec, action_from_dict,
)
from techs import load_techs

OP2_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
MAPS_VOL = OP2_DIR / "maps.vol"
CONFIG_PATH = EDITOR_DIR / "config.json"
SCENE_TILE = TILE  # native 32px -> scharf

# Standard-Ausgabeort der Mission-DLL. Colony-Missionen brauchen den Praefix "c".
DEFAULT_OUTPUT_DIR = str(OP2_DIR)
DEFAULT_DLL_NAME = "cEditorMission.dll"

# Gebaeude (Anzeige, map_id, Footprint aus building.txt)
STRUCTURES = [
    ("Command Center", "mapCommandCenter", (3, 2)),
    ("Tokamak", "mapTokamak", (2, 2)),
    ("Common Ore Smelter", "mapCommonOreSmelter", (4, 3)),
    ("Rare Ore Smelter", "mapRareOreSmelter", (4, 3)),
    ("Structure Factory", "mapStructureFactory", (4, 3)),
    ("Vehicle Factory", "mapVehicleFactory", (4, 3)),
    ("Arachnid Factory", "mapArachnidFactory", (4, 3)),
    ("Agridome", "mapAgridome", (3, 2)),
    ("Nursery", "mapNursery", (2, 2)),
    ("University", "mapUniversity", (2, 2)),
    ("Residence", "mapResidence", (2, 2)),
    ("Common Ore Mine", "mapCommonOreMine", (2, 1)),
    ("Rare Ore Mine", "mapRareOreMine", (2, 1)),
    ("Magma Well", "mapMagmaWell", (2, 1)),
    ("Spaceport", "mapSpaceport", (5, 4)),
    ("Guard Post", "mapGuardPost", (1, 1)),
]
VEHICLES = [
    ("Scout", "mapScout", (1, 1)),
    ("Cargo Truck", "mapCargoTruck", (1, 1)),
    ("ConVec", "mapConVec", (1, 1)),
    ("Robo-Miner", "mapRoboMiner", (1, 1)),
    ("Robo-Dozer", "mapRoboDozer", (1, 1)),
    ("Earthworker", "mapEarthworker", (1, 1)),
    ("Repair Vehicle", "mapRepairVehicle", (1, 1)),
    ("Lynx", "mapLynx", (1, 1)),
    ("Panther", "mapPanther", (1, 1)),
    ("Tiger", "mapTiger", (1, 1)),
]
# Mauern/Rohre (auch vom Trigger-Dialog genutzt)
WALL_ITEMS = [
    ("Rohr (Tube)", "mapTube", (1, 1)),
    ("Mauer (Wall)", "mapWall", (1, 1)),
    ("Lava-Mauer", "mapLavaWall", (1, 1)),
    ("Microbe-Mauer", "mapMicrobeWall", (1, 1)),
]
# Kategorie -> (kind, items)
CATALOG = {
    "Gebäude": ("structure", STRUCTURES),
    "Fahrzeuge": ("vehicle", VEHICLES),
    # Beacons, Magma Vents, Geysire, Mauern & Rohre in einer Kategorie.
    # Eintraege mit 4. Element ueberschreiben den Standard-Kind der Kategorie.
    "Beacons & Mauern": ("beacon", [
        ("Mining Beacon", "mapMiningBeacon", (1, 1)),
        ("Magma Vent", "mapMagmaVent", (1, 1)),
        ("Fumarole / Geysir", "mapFumarole", (1, 1)),
    ] + [(d, m, fp, "wall") for d, m, fp in WALL_ITEMS]),
}
# Einheiten/Gebaeude, die eine Waffe tragen koennen (Waffenauswahl beim Platzieren)
WEAPON_UNITS = {"mapLynx", "mapPanther", "mapTiger", "mapGuardPost"}
# Einheiten/Gebaeude fuer "Einheit erzeugen"-Aktionen (Anzeige -> map_id)
ALL_UNITS = [(d, m) for d, m, _ in STRUCTURES] + [(d, m) for d, m, _ in VEHICLES]
VEHICLE_UNITS = [(d, m) for d, m, _ in VEHICLES]
MILITARY_VEHICLES = [
    (d, m) for d, m, _ in VEHICLES
    if m in ("mapLynx", "mapPanther", "mapTiger")
]
SET_TARG_VEHICLES_BY_GROUP_TYPE = {
    "MiningGroup": [("Cargo Truck", "mapCargoTruck")],
    "BuildingGroup": [("ConVec", "mapConVec")],
    "ReinforceGroup": [],
    "FightGroup": MILITARY_VEHICLES,
}
STRUCTURE_FOOTPRINTS = {mid: fp for _, mid, fp in STRUCTURES}
WEAPONS = [
    ("Keine", "mapNone"),
    ("Laser", "mapLaser"),
    ("Microwave", "mapMicrowave"),
    ("Rail Gun", "mapRailGun"),
    ("RPG", "mapRPG"),
    ("EMP", "mapEMP"),
    ("ESG", "mapESG"),
    ("Stickyfoam", "mapStickyfoam"),
    ("Thor's Hammer", "mapThorsHammer"),
    ("Energy Cannon", "mapEnergyCannon"),
    ("Starflare", "mapStarflare"),
    ("Supernova", "mapSupernova"),
]

TRUCK_CARGO = {
    "Common Ore": "truckCommonOre", "Rare Ore": "truckRareOre",
    "Food": "truckFood", "Common Metal": "truckCommonMetal",
    "Rare Metal": "truckRareMetal", "Leer": "truckEmpty",
}
TRUCK_CARGO_BY_ID = {value: label for label, value in TRUCK_CARGO.items()}
ORE_TYPES = {"Zufällig": -1, "Common": 0, "Rare": 1}
YIELDS = {"Zufällig": -1, "Bar3 (viel)": 0, "Bar2 (mittel)": 1, "Bar1 (wenig)": 2}

PLAYER_COLORS = [QColor(80, 160, 255), QColor(255, 90, 90), QColor(90, 220, 90),
                 QColor(240, 220, 70), QColor(220, 120, 240), QColor(120, 230, 230)]
BEACON_COLOR = QColor(255, 200, 40)
WALL_COLOR = QColor(180, 180, 180)

# Sieg-/Niederlage-Bedingungen: Anzeige -> (kind, [genutzte Felder])
CONDITIONS = {
    "Zeit überstehen": ("time", ["marks", "objective"]),
    "Letzter Überlebender": ("lastStanding", []),
    "Raumschiff bauen": ("starship", []),
    "Gebäude-Anzahl": ("buildingCount", ["player", "count", "compare", "objective"]),
    "Fahrzeug-Anzahl": ("vehicleCount", ["player", "count", "compare", "objective"]),
    "Technologie erforscht": ("research", ["player", "tech_id", "objective"]),
    "Ressource erreicht": ("resource", ["player", "resource", "amount", "compare", "objective"]),
    "Gebäude operativ": ("operational", ["player", "building", "count", "compare", "objective"]),
    "Kein Command Center": ("noCC", ["player"]),
}
COMPARE = {"≥": "cmpGreaterEqual", "≤": "cmpLowerEqual", "=": "cmpEqual",
           ">": "cmpGreater", "<": "cmpLower"}
RESOURCES = {"Common Ore": "resCommonOre", "Rare Ore": "resRareOre", "Food": "resFood",
             "Kids": "resKids", "Workers": "resWorkers", "Scientists": "resScientists"}


# Trigger-Bedingungen: Anzeige -> (kind, [Felder])
TRIGGER_CONDITIONS = {
    "Zeit (Marks)": ("time", ["marks"]),
    "Punkt erreicht": ("point", ["player", "x", "y"]),
    "Rechteck betreten": ("rect", ["player", "x", "y", "width", "height"]),
    "Gebäude-Anzahl": ("buildingCount", ["player", "count", "compare"]),
    "Fahrzeug-Anzahl": ("vehicleCount", ["player", "count", "compare"]),
    "Technologie erforscht": ("research", ["player", "tech_id"]),
    "Ressource erreicht": ("resource", ["player", "resource", "amount", "compare"]),
    "Gebäude operativ": ("operational", ["player", "building", "count", "compare"]),
}
ACTION_KINDS = {
    "Leere Aktion (Platzhalter)": "noop",
    "Wenn / Dann / Sonst (Bedingungsblock)": "if",
    "Nachricht anzeigen": "message",
    "Einheit erzeugen": "createUnit",
    "Anderen Trigger erstellen (Laufzeit)": "createTrigger",
    "RecordBuilding": "recordBuilding",
    "RecordTube-Linie": "recordTube",
    "RecordWall-Linie": "recordWall",
    "SetTargCount": "setTargCount",
    "StartMiningOperation": "startMiningOperation",
    "Gebäude einer Gruppe zuweisen": "assignToGroup",
}
MINING_OPERATION_ORES = {
    "Common": "common",
    "Rare": "rare",
}
MINING_OPERATION_TYPES = {
    "common": ("mapCommonOreMine", "mapCommonOreSmelter"),
    "rare": ("mapRareOreMine", "mapRareOreSmelter"),
}


# IF-Bedingungen pro Aktion: Anzeige -> kind, und welche Felder genutzt werden
ACTION_CONDITION_KINDS = {
    "Gebäude an Position vorhanden": ("buildingAtLocation", ["player", "building", "x", "y"]),
    "Gebäude-Schaden an Position": ("unitDamage", ["player", "building", "x", "y", "compare", "value"]),
    "Spieler-Ressource": ("playerResource", ["player", "resource", "compare", "value"]),
    "Gebäude-Anzahl": ("buildingCount", ["player", "building", "compare", "value"]),
    "Technologie erforscht": ("hasTech", ["player", "tech_id"]),
}


def action_condition_summary(c) -> str:
    cmp = {v: k for k, v in COMPARE.items()}.get(c.compare, c.compare)
    neg = "NICHT " if c.negate else ""
    if c.kind == "buildingAtLocation":
        return f"{neg}{c.building_type} @ ({c.x},{c.y}) vorhanden (P{c.player})"
    if c.kind == "unitDamage":
        return f"{neg}Schaden {c.building_type} @ ({c.x},{c.y}) {cmp} {c.value} (P{c.player})"
    if c.kind == "playerResource":
        return f"{neg}{c.resource} {cmp} {c.value} (P{c.player})"
    if c.kind == "buildingCount":
        return f"{neg}Anzahl {c.building_type} {cmp} {c.value} (P{c.player})"
    if c.kind == "hasTech":
        return f"{neg}Tech {c.tech_id} erforscht (P{c.player})"
    return c.kind


def trigger_summary(t) -> str:
    cond = {v: k for k, (v, _) in TRIGGER_CONDITIONS.items()}.get(t.condition, t.condition)
    start = "Start" if t.enabled_at_start else "Laufzeit"
    return f"{t.name} [{start}] — {cond}, {len(t.actions)} Aktion(en)"


def action_summary(a) -> str:
    prefix = f"[IF×{len(a.conditions)}] " if getattr(a, "conditions", None) else ""
    return prefix + _action_summary_core(a)


def _action_summary_core(a) -> str:
    if a.kind == "noop":
        return "Leere Aktion (Platzhalter)"
    if a.kind == "if":
        logic = "ODER" if getattr(a, "condition_logic", "and") == "or" else "UND"
        return (f"Wenn ({len(getattr(a, 'conditions', []))} Bed., {logic}) → "
                f"Dann {len(getattr(a, 'then_actions', []))} / Sonst {len(getattr(a, 'else_actions', []))}")
    if a.kind == "message":
        return f"Nachricht: \"{a.text}\""
    if a.kind == "createUnit":
        weapon = "" if a.weapon_type == "mapNone" else f" / {a.weapon_type}"
        return f"Einheit: {a.unit_type}{weapon} @ ({a.x},{a.y}) P{a.player}"
    if a.kind == "createTrigger":
        return f"Trigger erstellen: {a.target}"
    if a.kind == "recordBuilding":
        return f"{a.group_name}.RecordBuilding({a.building_type} Mitte ({a.x},{a.y}))"
    if a.kind == "recordTube":
        return f"{a.group_name}.RecordTubeLine(({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "recordWall":
        return f"{a.group_name}.RecordWallLine({a.wall_type}, ({a.x},{a.y}) -> ({a.x2},{a.y2}))"
    if a.kind == "setTargCount":
        weapon = "" if a.weapon_type == "mapNone" else f", {a.weapon_type}"
        source = f" via {a.source_group_name} P{a.reinforce_priority}" if a.source_group_name else ""
        return f"{a.group_name}.SetTargCount({a.unit_type}{weapon}) = {a.target_count}{source}"
    if a.kind == "startMiningOperation":
        ore = "Rare" if a.ore_type == "rare" else "Common"
        mining_group = a.mining_group_name or "MiningGroup?"
        return (f"{mining_group}.StartMiningOperation({ore}, Builder {a.group_name}) "
                f"Mine ({a.x},{a.y}) -> Smelter ({a.x2},{a.y2}), "
                f"Rect ({a.rect_x},{a.rect_y}) {a.rect_width}x{a.rect_height}")
    if a.kind == "assignToGroup":
        return f"Wenn {a.building_type} @ ({a.x},{a.y}) gebaut -> {a.group_name}.TakeUnit (P{a.player})"
    return a.kind


def condition_summary(c: Condition) -> str:
    """Kurzbeschreibung einer Bedingung fuer die Liste."""
    cmp = {v: k for k, v in COMPARE.items()}.get(c.compare, c.compare)
    return {
        "time": f"Zeit überstehen: {c.marks} Marks",
        "lastStanding": "Letzter Überlebender",
        "starship": "Raumschiff bauen",
        "noCC": f"Kein Command Center (P{c.player})",
        "buildingCount": f"Gebäude {cmp} {c.count} (P{c.player})",
        "vehicleCount": f"Fahrzeuge {cmp} {c.count} (P{c.player})",
        "research": f"Tech {c.tech_id} erforscht (P{c.player})",
        "resource": f"{c.resource} {cmp} {c.amount} (P{c.player})",
        "operational": f"{c.building} operativ {cmp} {c.count} (P{c.player})",
    }.get(c.kind, c.kind)


def mining_group_summary(g: MiningGroupSpec) -> str:
    if not getattr(g, "has_setup", True):
        return f"{g.name} [MiningGroup] P{g.player}  leer, {len(g.truck_ids)} Truck(s)"
    return (f"{g.name} [MiningGroup] P{g.player}  Mine ({g.mine_x},{g.mine_y}) "
            f"-> Smelter ({g.smelter_x},{g.smelter_y}), {len(g.truck_ids)} Truck(s)")


def building_group_summary(g: BuildingGroupSpec) -> str:
    return (f"{g.name} [BuildingGroup] P{g.player}  Rect ({g.rect_x},{g.rect_y}) "
            f"{g.rect_width}x{g.rect_height}, {len(g.unit_ids)} Unit(s)")


def reinforce_group_summary(g: ReinforceGroupSpec) -> str:
    return (f"{g.name} [ReinforceGroup] P{g.player}  "
            f"{len(g.unit_ids)} Fabrik(en), {len(g.targets)} Zielgruppe(n)")

