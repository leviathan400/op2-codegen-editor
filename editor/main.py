"""OP2 Mission Editor -- GUI (Schritt C, Version 3).

Straenge: Karte rendern (mapview/) | Objekte per Klick ins Modell | Build -> DLL.
Neu in v3: Objekt-Kategorien (Gebaeude/Fahrzeuge/Beacons/Magma Vents/Geysire/
Mauern&Rohre), kontextabhaengige Parameter (Fracht, ConVec-Bausatz, Beacon-Ertrag),
korrekter Offset (+31/-1 ueber MkXY/XYPos im Codegen).
"""
from __future__ import annotations

import json
import shutil
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "codegen"))
sys.path.insert(0, str(ROOT / "mapview"))

from PySide6.QtCore import Qt, QRectF, QThread, QTimer, Signal
from PySide6.QtGui import QAction, QBrush, QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDockWidget,
    QFileDialog, QFormLayout, QGraphicsRectItem, QGraphicsScene,
    QGraphicsSimpleTextItem, QGraphicsView, QHBoxLayout, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPlainTextEdit,
    QProgressDialog, QPushButton, QSpinBox, QVBoxLayout, QWidget,
)
from PySide6.QtGui import QFont

from op2map import Op2Map
from render import render_array
from tileset import TILE
from vol import VolFile

import build as build_mod
from codegen import generate_levelmain
from mission_model import (
    BeaconSpec, BuildingGroupSpec, Colony, Condition, MiningGroupSpec, Mission,
    MissionType, PlayerSpec, ReinforceGroupSpec, ReinforceTargetSpec,
    StartMessage, TriggerAction, TriggerDef, UnitSpec, WallTubeSpec,
)
from techs import load_techs

OP2_DIR = Path(r"C:\Program Files (x86)\GOG Galaxy\Games\Outpost 2")
MAPS_VOL = OP2_DIR / "maps.vol"
CONFIG_PATH = HERE / "config.json"
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
# Kategorie -> (kind, items)
CATALOG = {
    "Gebäude": ("structure", STRUCTURES),
    "Fahrzeuge": ("vehicle", VEHICLES),
    "Beacons": ("beacon", [("Mining Beacon", "mapMiningBeacon", (1, 1))]),
    "Magma Vents": ("beacon", [("Magma Vent", "mapMagmaVent", (1, 1))]),
    "Geysire": ("beacon", [("Fumarole / Geysir", "mapFumarole", (1, 1))]),
    "Mauern & Rohre": ("wall", [
        ("Rohr (Tube)", "mapTube", (1, 1)),
        ("Mauer (Wall)", "mapWall", (1, 1)),
        ("Lava-Mauer", "mapLavaWall", (1, 1)),
        ("Microbe-Mauer", "mapMicrobeWall", (1, 1)),
    ]),
}
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
    "Nachricht anzeigen": "message",
    "Einheit erzeugen": "createUnit",
    "Anderen Trigger erstellen (Laufzeit)": "createTrigger",
    "RecordBuilding": "recordBuilding",
    "RecordTube-Linie": "recordTube",
    "RecordWall-Linie": "recordWall",
    "SetTargCount": "setTargCount",
    "StartMiningOperation": "startMiningOperation",
}
MINING_OPERATION_ORES = {
    "Common": "common",
    "Rare": "rare",
}
MINING_OPERATION_TYPES = {
    "common": ("mapCommonOreMine", "mapCommonOreSmelter"),
    "rare": ("mapRareOreMine", "mapRareOreSmelter"),
}


def trigger_summary(t) -> str:
    cond = {v: k for k, (v, _) in TRIGGER_CONDITIONS.items()}.get(t.condition, t.condition)
    start = "Start" if t.enabled_at_start else "Laufzeit"
    return f"{t.name} [{start}] — {cond}, {len(t.actions)} Aktion(en)"


def action_summary(a) -> str:
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


class PlacedObject:
    def __init__(self, kind, tx, ty, map_id, footprint, display, player, params, uid="", unit_name=""):
        self.kind = kind
        self.tile_x = tx
        self.tile_y = ty
        self.map_id = map_id
        self.footprint = footprint
        self.display = display
        self.player = player
        self.params = params
        self.uid = uid
        self.unit_name = unit_name
        self.items = []

    def covers(self, tx, ty):
        fw, fh = self.footprint
        x0, y0 = self.tile_x - fw // 2, self.tile_y - fh // 2
        return x0 <= tx < x0 + fw and y0 <= ty < y0 + fh

    def to_dict(self):
        return {"kind": self.kind, "tile_x": self.tile_x, "tile_y": self.tile_y,
                "map_id": self.map_id, "footprint": list(self.footprint),
                "display": self.display, "player": self.player, "params": self.params,
                "uid": self.uid, "unit_name": self.unit_name}

    @classmethod
    def from_dict(cls, d):
        return cls(d["kind"], d["tile_x"], d["tile_y"], d["map_id"],
                   tuple(d["footprint"]), d["display"], d["player"], d.get("params", {}),
                   d.get("uid", ""), d.get("unit_name", ""))


class MapView(QGraphicsView):
    tileClicked = Signal(int, int)
    tileRemoved = Signal(int, int)
    tileHover = Signal(int, int)
    rectDragStarted = Signal(int, int)
    rectDragMoved = Signal(int, int)
    rectDragFinished = Signal(int, int)
    rectDragCanceled = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self._panning = False
        self._pan_start = None
        self.rect_select_enabled = False
        self._rect_dragging = False

    def _tile(self, pos):
        sp = self.mapToScene(pos.toPoint())
        return int(sp.x() // SCENE_TILE), int(sp.y() // SCENE_TILE)

    def wheelEvent(self, event):
        f = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.LeftButton and self.rect_select_enabled:
            self._rect_dragging = True
            self.rectDragStarted.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton and self.rect_select_enabled:
            self._rect_dragging = False
            self.rectDragCanceled.emit()
        elif event.button() == Qt.LeftButton:
            self.tileClicked.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton:
            self.tileRemoved.emit(*self._tile(event.position()))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            d = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        if self._rect_dragging:
            self.rectDragMoved.emit(*self._tile(event.position()))
            return
        self.tileHover.emit(*self._tile(event.position()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
        elif event.button() == Qt.LeftButton and self._rect_dragging:
            self._rect_dragging = False
            self.rectDragFinished.emit(*self._tile(event.position()))
        else:
            super().mouseReleaseEvent(event)


class MapDialog(QDialog):
    def __init__(self, parent, names, current_map, mission_name):
        super().__init__(parent)
        self.setWindowTitle("Mission & Karte")
        self.name_edit = QLineEdit(mission_name)
        self.combo = QComboBox()
        self.combo.addItems(sorted(n for n in names if n.lower().endswith(".map")))
        if self.combo.findText(current_map) >= 0:
            self.combo.setCurrentText(current_map)
        form = QFormLayout()
        form.addRow("Missionsname:", self.name_edit)
        form.addRow("Karte:", self.combo)
        hint = QLabel("Der Missionsname wird in OP2 in der Missionsliste angezeigt.")
        hint.setStyleSheet("color: gray;")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(hint)
        lay.addWidget(btns)


class ObjectEditDialog(QDialog):
    def __init__(self, parent, obj: PlacedObject, num_players: int):
        super().__init__(parent)
        self.setWindowTitle(f"{obj.display} bearbeiten")
        self.obj = obj

        self.unit_name_edit = QLineEdit(obj.unit_name)
        self.unit_name_edit.setPlaceholderText("optional, z.B. mainSmelter")

        self.player_spin = QSpinBox()
        self.player_spin.setRange(0, max(0, num_players - 1))
        self.player_spin.setValue(max(0, min(obj.player, self.player_spin.maximum())))

        form = QFormLayout()
        form.addRow("Unit-Name:", self.unit_name_edit)
        form.addRow("Spieler:", self.player_spin)

        self.cargo_combo = None
        self.cargo_amount = None
        if obj.map_id == "mapCargoTruck":
            self.cargo_combo = QComboBox()
            self.cargo_combo.addItems(TRUCK_CARGO.keys())
            current_cargo = TRUCK_CARGO_BY_ID.get(obj.params.get("truck_cargo"), "Leer")
            self.cargo_combo.setCurrentText(current_cargo)
            self.cargo_amount = QSpinBox()
            self.cargo_amount.setRange(0, 5000)
            self.cargo_amount.setValue(obj.params.get("truck_amount", 0))
            form.addRow("Fracht:", self.cargo_combo)
            form.addRow("Menge:", self.cargo_amount)

        self.kit_combo = None
        if obj.map_id == "mapConVec":
            self.kit_combo = QComboBox()
            self.kit_combo.addItem("Leer", None)
            for display, map_id, _footprint in STRUCTURES:
                self.kit_combo.addItem(display, map_id)
            current_kit = obj.params.get("convec_kit")
            if current_kit is not None:
                index = self.kit_combo.findData(current_kit)
                if index >= 0:
                    self.kit_combo.setCurrentIndex(index)
            form.addRow("Bausatz:", self.kit_combo)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(btns)

    def apply_to(self, obj: PlacedObject):
        obj.unit_name = self.unit_name_edit.text().strip()
        obj.player = self.player_spin.value()
        if self.cargo_combo is not None and self.cargo_amount is not None:
            obj.params["truck_cargo"] = TRUCK_CARGO[self.cargo_combo.currentText()]
            obj.params["truck_amount"] = self.cargo_amount.value()
        if self.kit_combo is not None:
            obj.params["convec_kit"] = self.kit_combo.currentData()


class OutputDialog(QDialog):
    """Ausgabeort und Dateiname der erzeugten Mission-DLL."""
    def __init__(self, parent, out_dir, dll_name):
        super().__init__(parent)
        self.setWindowTitle("Ausgabeort der DLL")
        self.dir_edit = QLineEdit(out_dir)
        browse = QPushButton("Durchsuchen…")
        browse.clicked.connect(self._browse)
        dir_row = QWidget(); dr = QHBoxLayout(dir_row); dr.setContentsMargins(0, 0, 0, 0)
        dr.addWidget(self.dir_edit, 1); dr.addWidget(browse)

        self.name_edit = QLineEdit(dll_name)

        form = QFormLayout()
        form.addRow("Ordner:", dir_row)
        form.addRow("Dateiname:", self.name_edit)
        hint = QLabel("Hinweis: Colony-Missionen müssen mit „c“ beginnen,\n"
                      "z.B. cMeineMission.dll – sonst zeigt OP2 sie nicht an.")
        hint.setStyleSheet("color: gray;")
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addLayout(form); lay.addWidget(hint); lay.addWidget(btns)

    def _browse(self):
        d = QFileDialog.getExistingDirectory(self, "Ausgabeordner wählen", self.dir_edit.text())
        if d:
            self.dir_edit.setText(d)


class ConditionsDialog(QDialog):
    """Sieg- und Niederlage-Bedingungen zusammenstellen."""
    def __init__(self, parent, victories, defeats):
        super().__init__(parent)
        self.setWindowTitle("Sieg & Niederlage")
        self.resize(720, 460)
        self.victories = [Condition(**asdict(c)) for c in victories]
        self.defeats = [Condition(**asdict(c)) for c in defeats]

        # --- Formular (links) ---
        self.kind = QComboBox(); self.kind.addItems(CONDITIONS.keys())
        self.kind.currentTextChanged.connect(self._update_fields)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = QSpinBox(); self.marks.setRange(0, 200000); self.marks.setValue(600)
        self.count = QSpinBox(); self.count.setRange(0, 1000); self.count.setValue(1)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(1000)
        self.building = QComboBox()
        for disp, mid, _ in STRUCTURES:
            self.building.addItem(disp, mid)
        self.objective = QLineEdit("Mission abschließen.")

        self.form = QFormLayout()
        self.form.addRow("Typ:", self.kind)
        self._rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building, "objective": self.objective,
        }
        labels = {"player": "Spieler:", "marks": "Marks:", "count": "Anzahl:",
                  "compare": "Vergleich:", "tech_id": "Tech-ID:", "resource": "Ressource:",
                  "amount": "Menge:", "building": "Gebäude:", "objective": "Beschreibung:"}
        for key, w in self._rows.items():
            self.form.addRow(labels[key], w)

        add_win = QPushButton("→ als Sieg")
        add_win.clicked.connect(lambda: self._add(True))
        add_lose = QPushButton("→ als Niederlage")
        add_lose.clicked.connect(lambda: self._add(False))
        add_row = QHBoxLayout(); add_row.addWidget(add_win); add_row.addWidget(add_lose)

        left = QVBoxLayout()
        left.addLayout(self.form); left.addLayout(add_row); left.addStretch(1)

        # --- Listen (rechts) ---
        self.win_list = QListWidget()
        self.lose_list = QListWidget()
        rm_win = QPushButton("Ausgewählten Sieg entfernen")
        rm_win.clicked.connect(lambda: self._remove(True))
        rm_lose = QPushButton("Ausgewählte Niederlage entfernen")
        rm_lose.clicked.connect(lambda: self._remove(False))
        right = QVBoxLayout()
        right.addWidget(QLabel("Sieg-Bedingungen:")); right.addWidget(self.win_list)
        right.addWidget(rm_win)
        right.addWidget(QLabel("Niederlage-Bedingungen:")); right.addWidget(self.lose_list)
        right.addWidget(rm_lose)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(right, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh()
        self._update_fields()

    def _update_fields(self):
        fields = CONDITIONS[self.kind.currentText()][1]
        for key, w in self._rows.items():
            self.form.setRowVisible(w, key in fields)

    def _make(self) -> Condition:
        kind = CONDITIONS[self.kind.currentText()][0]
        return Condition(
            kind=kind, objective=self.objective.text(), player=self.player.value(),
            marks=self.marks.value(), count=self.count.value(),
            compare=COMPARE[self.compare.currentText()], tech_id=self.tech_id.value(),
            resource=RESOURCES[self.resource.currentText()], amount=self.amount.value(),
            building=self.building.currentData(),
        )

    def _add(self, is_victory):
        (self.victories if is_victory else self.defeats).append(self._make())
        self._refresh()

    def _remove(self, is_victory):
        lst = self.win_list if is_victory else self.lose_list
        data = self.victories if is_victory else self.defeats
        row = lst.currentRow()
        if 0 <= row < len(data):
            del data[row]
            self._refresh()

    def _refresh(self):
        self.win_list.clear(); self.lose_list.clear()
        for c in self.victories:
            self.win_list.addItem(condition_summary(c))
        for c in self.defeats:
            self.lose_list.addItem(condition_summary(c))


class PlayersDialog(QDialog):
    """Spieler verwalten: Kolonie, Mensch/KI, Tech-Level, Kolonisten, Forschungen."""
    def __init__(self, parent, players):
        super().__init__(parent)
        self.setWindowTitle("Spieler")
        self.resize(640, 480)
        self.players = [PlayerSpec(**asdict(p)) for p in players] or [PlayerSpec()]
        self._idx = 0
        self._loading = False
        self.all_techs = load_techs(OP2_DIR / "multitek.txt")  # (id, name), sortiert
        self.tech_names = {tid: name for tid, name in self.all_techs}

        self.plist = QListWidget()
        add = QPushButton("Spieler hinzufügen"); add.clicked.connect(self._add)
        rm = QPushButton("Entfernen"); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(self.plist, 1); left.addWidget(add); left.addWidget(rm)

        self.colony = QComboBox(); self.colony.addItems(["Eden", "Plymouth"])
        self.ptype = QComboBox(); self.ptype.addItems(["Mensch", "KI"])
        self.tech = QSpinBox(); self.tech.setRange(0, 12)
        self.init_res = QCheckBox("Startressourcen setzen")
        self.set_pop = QCheckBox("Kolonisten explizit setzen")
        self.workers = QSpinBox(); self.workers.setRange(0, 5000)
        self.scientists = QSpinBox(); self.scientists.setRange(0, 5000)
        self.kids = QSpinBox(); self.kids.setRange(0, 5000)
        self.set_res = QCheckBox("Ressourcen explizit setzen")
        self.common = QSpinBox(); self.common.setRange(0, 1000000)
        self.rare = QSpinBox(); self.rare.setRange(0, 1000000)
        self.food = QSpinBox(); self.food.setRange(0, 1000000)

        # Forschungen: Auswahl per Name + "Tech hinzufügen" + Liste
        self.tech_avail = QComboBox()
        add_tech = QPushButton("Tech hinzufügen")
        add_tech.clicked.connect(self._add_tech)
        tech_add_row = QWidget(); tar = QHBoxLayout(tech_add_row); tar.setContentsMargins(0, 0, 0, 0)
        tar.addWidget(self.tech_avail, 1); tar.addWidget(add_tech)
        self.research_list = QListWidget()
        self.research_list.setMaximumHeight(110)
        rm_tech = QPushButton("Forschung entfernen")
        rm_tech.clicked.connect(self._remove_tech)

        form = QFormLayout()
        form.addRow("Kolonie:", self.colony)
        form.addRow("Typ:", self.ptype)
        form.addRow("Tech-Level:", self.tech)
        form.addRow(self.init_res)
        form.addRow(self.set_pop)
        form.addRow("Arbeiter:", self.workers)
        form.addRow("Wissenschaftler:", self.scientists)
        form.addRow("Kinder:", self.kids)
        form.addRow(self.set_res)
        form.addRow("Common Ore:", self.common)
        form.addRow("Rare Ore:", self.rare)
        form.addRow("Nahrung:", self.food)
        form.addRow("Forschung:", tech_add_row)
        form.addRow("Vorab erforscht:", self.research_list)
        form.addRow("", rm_tech)

        # bei jeder Aenderung in den aktuellen Spieler schreiben
        for w in (self.colony, self.ptype):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.workers, self.scientists, self.kids,
                  self.common, self.rare, self.food):
            w.valueChanged.connect(self._store_current)
        for w in (self.init_res, self.set_pop, self.set_res):
            w.toggled.connect(self._store_current)
        # Tech-Level beeinflusst auch die verfuegbaren Forschungen
        self.tech.valueChanged.connect(self._on_tech_level_changed)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(form, 2)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self.plist.currentRowChanged.connect(self._on_select)
        self._refresh_list()
        self.plist.setCurrentRow(0)

    def _label(self, i, p):
        return f"Spieler {i} — {'Eden' if p.colony == Colony.Eden else 'Plymouth'}, " \
               f"{'Mensch' if p.is_human else 'KI'}, Tech {p.tech_level}"

    def _refresh_list(self):
        self.plist.blockSignals(True)
        cur = self.plist.currentRow()
        self.plist.clear()
        for i, p in enumerate(self.players):
            self.plist.addItem(self._label(i, p))
        self.plist.setCurrentRow(min(max(cur, 0), len(self.players) - 1))
        self.plist.blockSignals(False)

    def _on_select(self, row):
        if row < 0:
            return
        self._idx = row
        self._load(row)

    def _load(self, i):
        p = self.players[i]
        self._loading = True
        self.colony.setCurrentText("Eden" if p.colony == Colony.Eden else "Plymouth")
        self.ptype.setCurrentText("Mensch" if p.is_human else "KI")
        self.tech.setValue(p.tech_level)
        self.init_res.setChecked(p.init_resources)
        self.set_pop.setChecked(p.workers is not None or p.scientists is not None or p.kids is not None)
        self.workers.setValue(p.workers or 0)
        self.scientists.setValue(p.scientists or 0)
        self.kids.setValue(p.kids or 0)
        self.set_res.setChecked(p.common_ore is not None or p.rare_ore is not None or p.food is not None)
        self.common.setValue(p.common_ore or 0)
        self.rare.setValue(p.rare_ore or 0)
        self.food.setValue(p.food or 0)
        self._loading = False
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.players)):
            return
        # Forschungen werden separat (Hinzufügen/Entfernen) verwaltet -> uebernehmen.
        researches = list(self.players[self._idx].researches)
        p = PlayerSpec(
            colony=Colony.Eden if self.colony.currentText() == "Eden" else Colony.Plymouth,
            is_human=(self.ptype.currentText() == "Mensch"),
            tech_level=self.tech.value(),
            init_resources=self.init_res.isChecked(),
            workers=self.workers.value() if self.set_pop.isChecked() else None,
            scientists=self.scientists.value() if self.set_pop.isChecked() else None,
            kids=self.kids.value() if self.set_pop.isChecked() else None,
            common_ore=self.common.value() if self.set_res.isChecked() else None,
            rare_ore=self.rare.value() if self.set_res.isChecked() else None,
            food=self.food.value() if self.set_res.isChecked() else None,
            researches=researches,
        )
        self.players[self._idx] = p
        item = self.plist.item(self._idx)
        if item:
            item.setText(self._label(self._idx, p))

    def _on_tech_level_changed(self):
        if self._loading or not (0 <= self._idx < len(self.players)):
            return
        self._store_current()  # uebernimmt neues Tech-Level
        lvl = self.players[self._idx].tech_level
        # Bereits durch das Tech-Level abgedeckte Forschungen entfernen.
        self.players[self._idx].researches = [
            t for t in self.players[self._idx].researches if t > lvl * 1000]
        self._refresh_tech_avail(lvl)
        self._refresh_research_list()

    def _refresh_tech_avail(self, tech_level: int):
        """Verfuegbare Techs = die NICHT schon durch das Tech-Level vergeben sind."""
        self.tech_avail.clear()
        threshold = tech_level * 1000
        already = set(self.players[self._idx].researches) if 0 <= self._idx < len(self.players) else set()
        for tid, name in self.all_techs:
            if tid <= threshold or tid in already or name == "NOT AVAILABLE":
                continue
            self.tech_avail.addItem(f"{name}  ({tid})", tid)

    def _refresh_research_list(self):
        self.research_list.clear()
        if not (0 <= self._idx < len(self.players)):
            return
        for tid in self.players[self._idx].researches:
            name = self.tech_names.get(tid, "?")
            it = QListWidgetItem(f"{name}  ({tid})")
            it.setData(Qt.UserRole, tid)
            self.research_list.addItem(it)

    def _add_tech(self):
        tid = self.tech_avail.currentData()
        if tid is None or not (0 <= self._idx < len(self.players)):
            return
        p = self.players[self._idx]
        if tid not in p.researches:
            p.researches.append(tid)
            p.researches.sort()
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _remove_tech(self):
        it = self.research_list.currentItem()
        if it is None or not (0 <= self._idx < len(self.players)):
            return
        tid = it.data(Qt.UserRole)
        p = self.players[self._idx]
        if tid in p.researches:
            p.researches.remove(tid)
        self._refresh_tech_avail(p.tech_level)
        self._refresh_research_list()

    def _add(self):
        self.players.append(PlayerSpec())
        self._refresh_list()
        self.plist.setCurrentRow(len(self.players) - 1)

    def _remove(self):
        if len(self.players) <= 1:
            return
        del self.players[self._idx]
        self._idx = max(0, self._idx - 1)
        self._refresh_list()
        self.plist.setCurrentRow(self._idx)


class TriggersDialog(QDialog):
    """Benutzerdefinierte Trigger: Bedingung + Aktionen, mit Laufzeit-Erstellung."""
    def __init__(
        self, parent, triggers, building_groups=None, target_groups=None,
        reinforce_groups=None, mining_groups=None, objects=None, initial_trigger_index=0,
        initial_action_index=-1,
    ):
        super().__init__(parent)
        self.setWindowTitle("Trigger")
        self.resize(900, 620)
        self.triggers = [self._copy(t) for t in triggers]
        self.building_groups = list(building_groups or [])
        self.mining_groups = list(mining_groups or [])
        self.objects = list(objects or [])
        self.trucks = [o for o in self.objects if o.map_id == "mapCargoTruck"]
        self.target_groups = list(target_groups or self.building_groups)
        self.reinforce_groups = list(reinforce_groups or [])
        self.target_group_types = {
            group.name: (
                "MiningGroup" if isinstance(group, MiningGroupSpec)
                else "BuildingGroup" if isinstance(group, BuildingGroupSpec)
                else "FightGroup"
            )
            for group in self.target_groups
        }
        self._idx = -1
        self._initial_trigger_index = initial_trigger_index
        self._initial_action_index = initial_action_index
        self._loading = False
        self.map_pick_request = None

        # --- Trigger-Liste ---
        self.tlist = QListWidget()
        self.tlist.currentRowChanged.connect(self._on_select)
        add = QPushButton("Trigger hinzufügen"); add.clicked.connect(self._add)
        rm = QPushButton("Trigger entfernen"); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel("Trigger:")); left.addWidget(self.tlist, 1)
        left.addWidget(add); left.addWidget(rm)

        # --- Trigger-Eigenschaften ---
        self.name = QLineEdit()
        self.at_start = QCheckBox("Beim Start aktiv (sonst nur per Laufzeit-Erstellung)")
        self.one_shot = QCheckBox("Nur einmal auslösen")
        self.cond = QComboBox(); self.cond.addItems(TRIGGER_CONDITIONS.keys())
        self.cond.currentTextChanged.connect(self._update_cond_fields)
        self.player = QSpinBox(); self.player.setRange(0, 5)
        self.marks = QSpinBox(); self.marks.setRange(0, 200000); self.marks.setValue(100)
        self.count = QSpinBox(); self.count.setRange(0, 1000); self.count.setValue(1)
        self.compare = QComboBox(); self.compare.addItems(COMPARE.keys())
        self.tech_id = QSpinBox(); self.tech_id.setRange(0, 20000)
        self.resource = QComboBox(); self.resource.addItems(RESOURCES.keys())
        self.amount = QSpinBox(); self.amount.setRange(0, 1000000); self.amount.setValue(1000)
        self.building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.building.addItem(d, m)
        self.x = QSpinBox(); self.x.setRange(0, 1023)
        self.y = QSpinBox(); self.y.setRange(0, 1023)
        self.width = QSpinBox(); self.width.setRange(1, 256); self.width.setValue(4)
        self.height = QSpinBox(); self.height.setRange(1, 256); self.height.setValue(4)

        self.form = QFormLayout()
        self.form.addRow("Name:", self.name)
        self.form.addRow(self.at_start)
        self.form.addRow(self.one_shot)
        self.form.addRow("Bedingung:", self.cond)
        self._cond_rows = {
            "player": self.player, "marks": self.marks, "count": self.count,
            "compare": self.compare, "tech_id": self.tech_id, "resource": self.resource,
            "amount": self.amount, "building": self.building,
            "x": self.x, "y": self.y, "width": self.width, "height": self.height,
        }
        clabels = {"player": "Spieler:", "marks": "Marks:", "count": "Anzahl:",
                   "compare": "Vergleich:", "tech_id": "Tech-ID:", "resource": "Ressource:",
                   "amount": "Menge:", "building": "Gebäude:", "x": "X:", "y": "Y:",
                   "width": "Breite:", "height": "Höhe:"}
        for key, w in self._cond_rows.items():
            self.form.addRow(clabels[key], w)

        self.name.textChanged.connect(self._store_current)
        for w in (self.cond, self.compare, self.resource, self.building):
            w.currentIndexChanged.connect(self._store_current)
        for w in (self.player, self.marks, self.count, self.tech_id, self.amount,
                  self.x, self.y, self.width, self.height):
            w.valueChanged.connect(self._store_current)
        for w in (self.at_start, self.one_shot):
            w.toggled.connect(self._store_current)

        # --- Aktionen ---
        self.alist = QListWidget(); self.alist.setMaximumHeight(120)
        self.alist.currentRowChanged.connect(self._on_action_select)
        self.act_kind = QComboBox(); self.act_kind.addItems(ACTION_KINDS.keys())
        self.act_kind.currentTextChanged.connect(self._update_action_fields)
        self.act_text = QLineEdit("Nachricht…")
        self.act_unit = QComboBox()
        for d, m in ALL_UNITS:
            self.act_unit.addItem(d, m)
        self.act_vehicle = QComboBox()
        for d, m in VEHICLE_UNITS:
            self.act_vehicle.addItem(d, m)
        self.act_weapon = QComboBox()
        for d, m in WEAPONS:
            self.act_weapon.addItem(d, m)
        self.act_target_count = QSpinBox(); self.act_target_count.setRange(0, 1000); self.act_target_count.setValue(1)
        self.act_priority = QSpinBox(); self.act_priority.setRange(1, 65535); self.act_priority.setValue(1000)
        self.act_ore = QComboBox()
        self.act_ore.addItems(MINING_OPERATION_ORES.keys())
        self.act_rect_x = QSpinBox(); self.act_rect_x.setRange(0, 1023)
        self.act_rect_y = QSpinBox(); self.act_rect_y.setRange(0, 1023)
        self.act_rect_w = QSpinBox(); self.act_rect_w.setRange(1, 256); self.act_rect_w.setValue(8)
        self.act_rect_h = QSpinBox(); self.act_rect_h.setRange(1, 256); self.act_rect_h.setValue(8)
        self.act_truck_count = QSpinBox(); self.act_truck_count.setRange(0, 50); self.act_truck_count.setValue(0)
        self.act_mining_group = QComboBox()
        for group in self.mining_groups:
            self.act_mining_group.addItem(f"{group.name} [MiningGroup]", group.name)
        self.act_x = QSpinBox(); self.act_x.setRange(0, 1023)
        self.act_y = QSpinBox(); self.act_y.setRange(0, 1023)
        self.act_x2 = QSpinBox(); self.act_x2.setRange(0, 1023)
        self.act_y2 = QSpinBox(); self.act_y2.setRange(0, 1023)
        self.act_player = QSpinBox(); self.act_player.setRange(0, 5)
        self.act_target = QComboBox()
        self.act_group = QComboBox()
        for group in self.building_groups:
            self.act_group.addItem(f"{group.name} [BuildingGroup]", group.name)
        self.act_target_group = QComboBox()
        for group in self.target_groups:
            group_type = self.target_group_types.get(group.name, "BuildingGroup")
            self.act_target_group.addItem(f"{group.name} [{group_type}]", group.name)
        self.act_target_group.currentIndexChanged.connect(self._update_set_targ_vehicle_options)
        self.act_source_group = QComboBox()
        for group in self.reinforce_groups:
            self.act_source_group.addItem(f"{group.name} [ReinforceGroup]", group.name)
        self.act_building = QComboBox()
        for d, m, _ in STRUCTURES:
            self.act_building.addItem(d, m)
        self.act_wall = QComboBox()
        for d, m, _ in CATALOG["Mauern & Rohre"][1]:
            if m != "mapTube":
                self.act_wall.addItem(d, m)
        self.act_form = QFormLayout()
        self.act_form.addRow("Aktionstyp:", self.act_kind)
        self._act_rows = {"text": self.act_text, "unit": self.act_unit,
                          "vehicle": self.act_vehicle, "weapon": self.act_weapon,
                          "target_count": self.act_target_count, "priority": self.act_priority,
                          "ore": self.act_ore,
                          "rect_x": self.act_rect_x, "rect_y": self.act_rect_y,
                          "rect_w": self.act_rect_w, "rect_h": self.act_rect_h,
                          "truck_count": self.act_truck_count,
                          "mining_group": self.act_mining_group,
                          "x": self.act_x,
                          "y": self.act_y, "x2": self.act_x2, "y2": self.act_y2,
                          "player": self.act_player, "target": self.act_target,
                          "target_group": self.act_target_group,
                          "source_group": self.act_source_group,
                          "group": self.act_group, "building": self.act_building,
                          "wall": self.act_wall}
        alabels = {"text": "Text:", "unit": "Einheit:", "vehicle": "Fahrzeug:",
                   "weapon": "Waffe/Cargo:", "target_count": "Zielanzahl:",
                   "priority": "Prioritaet:",
                   "ore": "Erz:", "rect_x": "Smelter-Rect X:",
                   "rect_y": "Smelter-Rect Y:", "rect_w": "Smelter-Rect Breite:",
                   "rect_h": "Smelter-Rect Hoehe:", "truck_count": "Transporter (Zielanzahl):",
                   "mining_group": "MiningGroup:",
                   "x": "X / Mine X:", "y": "Y / Mine Y:",
                   "x2": "X2 / Smelter X:", "y2": "Y2 / Smelter Y:", "player": "Spieler:",
                   "target": "Ziel-Trigger:", "group": "BuildingGroup:",
                   "target_group": "Zielgruppe:", "source_group": "ReinforceGroup:",
                   "building": "Gebaeude:", "wall": "Wall/Tube:"}
        for key, w in self._act_rows.items():
            self.act_form.addRow(alabels[key], w)
        add_act = QPushButton("Aktion hinzufügen"); add_act.clicked.connect(self._add_action)
        self.pick_on_map = QPushButton("Aktion auf Karte setzen")
        self.pick_on_map.clicked.connect(self._pick_action_on_map)
        self.act_form.addRow("", self.pick_on_map)
        self.pick_mining_mine = QPushButton("Mine auf Karte setzen")
        self.pick_mining_mine.clicked.connect(lambda: self._pick_mining_operation_on_map("mine"))
        self.act_form.addRow("", self.pick_mining_mine)
        self.pick_mining_smelter = QPushButton("Smelter auf Karte setzen")
        self.pick_mining_smelter.clicked.connect(lambda: self._pick_mining_operation_on_map("smelter"))
        self.act_form.addRow("", self.pick_mining_smelter)
        self.pick_mining_rect = QPushButton("Smelter-Rect auf Karte ziehen")
        self.pick_mining_rect.clicked.connect(lambda: self._pick_mining_operation_on_map("rect"))
        self.act_form.addRow("", self.pick_mining_rect)
        update_act = QPushButton("Aktion aktualisieren"); update_act.clicked.connect(self._update_action)
        rm_act = QPushButton("Aktion entfernen"); rm_act.clicked.connect(self._remove_action)
        act_btns = QHBoxLayout(); act_btns.addWidget(add_act); act_btns.addWidget(update_act); act_btns.addWidget(rm_act)

        mid = QVBoxLayout()
        mid.addLayout(self.form)
        mid.addStretch(1)
        right = QVBoxLayout()
        right.addWidget(QLabel("Aktionen (laufen beim Auslösen):"))
        right.addWidget(self.alist)
        right.addLayout(self.act_form)
        right.addLayout(act_btns)
        right.addStretch(1)

        body = QHBoxLayout()
        body.addLayout(left, 1); body.addLayout(mid, 1); body.addLayout(right, 1)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh_list()
        if self.triggers:
            self.tlist.setCurrentRow(max(0, min(self._initial_trigger_index, len(self.triggers) - 1)))
            if self._initial_action_index >= 0:
                self.alist.setCurrentRow(self._initial_action_index)
        else:
            self._set_form_enabled(False)
        self._update_action_fields()

    @staticmethod
    def _copy(t):
        d = asdict(t)
        acts = [TriggerAction(**a) for a in d.pop("actions", [])]
        return TriggerDef(actions=acts, **d)

    def _set_form_enabled(self, on):
        for w in list(self._cond_rows.values()) + [self.name, self.at_start, self.one_shot,
                                                    self.cond, self.alist]:
            w.setEnabled(on)

    # --- Trigger-Liste ---
    def _refresh_list(self):
        self.tlist.blockSignals(True)
        cur = self.tlist.currentRow()
        self.tlist.clear()
        for t in self.triggers:
            self.tlist.addItem(trigger_summary(t))
        if 0 <= cur < len(self.triggers):
            self.tlist.setCurrentRow(cur)
        self.tlist.blockSignals(False)

    def _on_select(self, row):
        if not (0 <= row < len(self.triggers)):
            self._idx = -1
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        self._idx = row
        self._load(row)

    def _add(self):
        name = f"Trigger{len(self.triggers) + 1}"
        self.triggers.append(TriggerDef(name=name))
        self._refresh_list()
        self.tlist.setCurrentRow(len(self.triggers) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        del self.triggers[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.triggers:
            self.tlist.setCurrentRow(min(self.tlist.currentRow(), len(self.triggers) - 1))
        else:
            self._set_form_enabled(False)

    # --- Eigenschaften laden/speichern ---
    def _load(self, i):
        t = self.triggers[i]
        self._loading = True
        self.name.setText(t.name)
        self.at_start.setChecked(t.enabled_at_start)
        self.one_shot.setChecked(t.one_shot)
        disp = {v: k for k, (v, _) in TRIGGER_CONDITIONS.items()}.get(t.condition, "Zeit (Marks)")
        self.cond.setCurrentText(disp)
        self.player.setValue(t.player); self.marks.setValue(t.marks)
        self.count.setValue(t.count)
        self.compare.setCurrentText({v: k for k, v in COMPARE.items()}.get(t.compare, "≥"))
        self.tech_id.setValue(t.tech_id)
        self.resource.setCurrentText({v: k for k, v in RESOURCES.items()}.get(t.resource, "Common Ore"))
        self.amount.setValue(t.amount)
        bidx = self.building.findData(t.building)
        if bidx >= 0:
            self.building.setCurrentIndex(bidx)
        self.x.setValue(t.x); self.y.setValue(t.y)
        self.width.setValue(t.width); self.height.setValue(t.height)
        self._loading = False
        self._update_cond_fields()
        self._refresh_actions()

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.triggers)):
            return
        t = self.triggers[self._idx]
        t.name = self.name.text() or f"Trigger{self._idx + 1}"
        t.enabled_at_start = self.at_start.isChecked()
        t.one_shot = self.one_shot.isChecked()
        t.condition = TRIGGER_CONDITIONS[self.cond.currentText()][0]
        t.player = self.player.value(); t.marks = self.marks.value()
        t.count = self.count.value(); t.compare = COMPARE[self.compare.currentText()]
        t.tech_id = self.tech_id.value()
        t.resource = RESOURCES[self.resource.currentText()]
        t.amount = self.amount.value(); t.building = self.building.currentData()
        t.x = self.x.value(); t.y = self.y.value()
        t.width = self.width.value(); t.height = self.height.value()
        item = self.tlist.item(self._idx)
        if item:
            item.setText(trigger_summary(t))

    def _update_cond_fields(self):
        fields = TRIGGER_CONDITIONS[self.cond.currentText()][1]
        for key, w in self._cond_rows.items():
            self.form.setRowVisible(w, key in fields)

    # --- Aktionen ---
    def _refresh_actions(self):
        self.alist.clear()
        if not (0 <= self._idx < len(self.triggers)):
            return
        for a in self.triggers[self._idx].actions:
            self.alist.addItem(action_summary(a))
        # Ziel-Trigger-Auswahl aktualisieren (andere Trigger)
        self.act_target.clear()
        for t in self.triggers:
            if t is not self.triggers[self._idx]:
                self.act_target.addItem(t.name, t.name)

    def _set_combo_data(self, combo, value):
        index = combo.findData(value)
        if index >= 0:
            combo.setCurrentIndex(index)

    def _set_action_kind(self, kind):
        for label, value in ACTION_KINDS.items():
            if value == kind:
                self.act_kind.setCurrentText(label)
                return

    def _on_action_select(self, row):
        if not (0 <= self._idx < len(self.triggers)):
            return
        actions = self.triggers[self._idx].actions
        if not (0 <= row < len(actions)):
            return
        self._load_action(actions[row])

    def _load_action(self, action):
        self._set_action_kind(action.kind)
        self.act_text.setText(action.text)
        self._set_combo_data(self.act_unit, action.unit_type)
        self._set_combo_data(self.act_weapon, action.weapon_type)
        self._set_combo_data(self.act_vehicle, action.unit_type)
        self.act_target_count.setValue(action.target_count)
        self.act_priority.setValue(action.reinforce_priority)
        self.act_x.setValue(action.x)
        self.act_y.setValue(action.y)
        self.act_x2.setValue(action.x2)
        self.act_y2.setValue(action.y2)
        self.act_rect_x.setValue(action.rect_x)
        self.act_rect_y.setValue(action.rect_y)
        self.act_rect_w.setValue(action.rect_width)
        self.act_rect_h.setValue(action.rect_height)
        self.act_truck_count.setValue(getattr(action, "truck_count", 0))
        self.act_player.setValue(action.player)
        self._set_combo_data(self.act_target, action.target)
        self._set_combo_data(self.act_group, action.group_name)
        self._set_combo_data(self.act_target_group, action.group_name)
        self._set_combo_data(self.act_mining_group, action.mining_group_name)
        self._set_combo_data(self.act_source_group, action.source_group_name)
        self._set_combo_data(self.act_building, action.building_type)
        self._set_combo_data(self.act_wall, action.wall_type)
        ore_label = {value: label for label, value in MINING_OPERATION_ORES.items()}.get(action.ore_type)
        if ore_label:
            self.act_ore.setCurrentText(ore_label)
        self._update_action_fields()

    def _update_action_fields(self):
        kind = ACTION_KINDS[self.act_kind.currentText()]
        vis = {"text": kind == "message",
               "unit": kind == "createUnit",
               "x": kind in ("createUnit", "startMiningOperation"),
               "y": kind in ("createUnit", "startMiningOperation"),
               "vehicle": kind == "setTargCount",
               "weapon": kind == "createUnit",
               "target_count": kind == "setTargCount",
               "priority": kind == "setTargCount",
               "ore": kind == "startMiningOperation",
               "rect_x": kind == "startMiningOperation",
               "rect_y": kind == "startMiningOperation",
               "rect_w": kind == "startMiningOperation",
               "rect_h": kind == "startMiningOperation",
               "truck_count": kind == "startMiningOperation",
               "mining_group": kind == "startMiningOperation",
               "x2": kind == "startMiningOperation",
               "y2": kind == "startMiningOperation",
               "player": kind in ("createUnit", "startMiningOperation"),
               "target": kind == "createTrigger",
               "group": kind in ("recordBuilding", "recordTube", "recordWall", "startMiningOperation"),
               "target_group": kind == "setTargCount",
               "source_group": kind == "setTargCount",
               "building": kind == "recordBuilding",
               "wall": kind == "recordWall"}
        if kind == "recordBuilding":
            vis["x"] = True
            vis["y"] = True
        if kind in ("recordTube", "recordWall"):
            vis["x"] = True
            vis["y"] = True
            vis["x2"] = True
            vis["y2"] = True
        for key, w in self._act_rows.items():
            self.act_form.setRowVisible(w, vis[key])
        self.pick_on_map.setVisible(kind in ("recordBuilding", "recordTube", "recordWall"))
        self.pick_mining_mine.setVisible(kind == "startMiningOperation")
        self.pick_mining_smelter.setVisible(kind == "startMiningOperation")
        self.pick_mining_rect.setVisible(kind == "startMiningOperation")
        self._update_set_targ_vehicle_options()

    def _object_label(self, obj):
        name = f"{obj.unit_name}: " if obj.unit_name else ""
        return f"{name}{obj.display} P{obj.player} @ ({obj.tile_x},{obj.tile_y})"

    def _update_set_targ_vehicle_options(self):
        current = self.act_vehicle.currentData()
        group_name = self.act_target_group.currentData()
        group_type = self.target_group_types.get(group_name, "BuildingGroup")
        vehicles = SET_TARG_VEHICLES_BY_GROUP_TYPE.get(group_type, [])
        self.act_vehicle.blockSignals(True)
        self.act_vehicle.clear()
        for display, map_id in vehicles:
            self.act_vehicle.addItem(display, map_id)
        if current is not None:
            index = self.act_vehicle.findData(current)
            if index >= 0:
                self.act_vehicle.setCurrentIndex(index)
        self.act_vehicle.blockSignals(False)

    def _selected_building_group(self):
        group_name = self.act_group.currentData()
        if not group_name:
            QMessageBox.information(self, "Keine BuildingGroup", "Lege zuerst eine BuildingGroup an.")
            return None
        return group_name

    def _selected_set_targ_groups(self):
        target_group_name = self.act_target_group.currentData()
        if not target_group_name:
            QMessageBox.information(self, "Keine Zielgruppe", "Lege zuerst eine MiningGroup oder BuildingGroup an.")
            return None, None
        source_group_name = self.act_source_group.currentData()
        if not source_group_name:
            QMessageBox.information(self, "Keine ReinforceGroup", "Lege zuerst eine ReinforceGroup mit Vehicle Factories an.")
            return None, None
        if self.act_vehicle.currentData() is None:
            group_type = self.target_group_types.get(target_group_name, "BuildingGroup")
            QMessageBox.information(
                self, "Kein erlaubtes Fahrzeug",
                f"Fuer {group_type} ist aktuell kein passender Fahrzeugtyp verfuegbar.")
            return None, None
        return target_group_name, source_group_name

    def _selected_mining_group(self):
        group_name = self.act_mining_group.currentData()
        if not group_name:
            QMessageBox.information(self, "Keine MiningGroup", "Lege zuerst eine MiningGroup an.")
            return None
        return group_name

    def _pick_action_on_map(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        kind = ACTION_KINDS[self.act_kind.currentText()]
        if kind not in ("recordBuilding", "recordTube", "recordWall"):
            return
        group_name = self._selected_building_group()
        if not group_name:
            return
        mining_group_name = self._selected_mining_group()
        if not mining_group_name:
            return
        self.map_pick_request = {
            "trigger_index": self._idx,
            "kind": kind,
            "group_name": group_name,
            "mining_group_name": mining_group_name,
            "building_type": self.act_building.currentData(),
            "wall_type": self.act_wall.currentData(),
        }
        self.accept()

    def _pick_mining_operation_on_map(self, mode):
        if not (0 <= self._idx < len(self.triggers)):
            return
        if ACTION_KINDS[self.act_kind.currentText()] != "startMiningOperation":
            return
        group_name = self._selected_building_group()
        if not group_name:
            return
        mining_group_name = self._selected_mining_group()
        if not mining_group_name:
            return
        action_index = self.alist.currentRow()
        if not (
            0 <= action_index < len(self.triggers[self._idx].actions)
            and self.triggers[self._idx].actions[action_index].kind == "startMiningOperation"
        ):
            action_index = -1
        self.map_pick_request = {
            "trigger_index": self._idx,
            "kind": "startMiningOperation",
            "mode": mode,
            "group_name": group_name,
            "mining_group_name": mining_group_name,
            "ore_type": MINING_OPERATION_ORES[self.act_ore.currentText()],
            "truck_count": self.act_truck_count.value(),
            "x": self.act_x.value(),
            "y": self.act_y.value(),
            "x2": self.act_x2.value(),
            "y2": self.act_y2.value(),
            "rect_x": self.act_rect_x.value(),
            "rect_y": self.act_rect_y.value(),
            "rect_width": self.act_rect_w.value(),
            "rect_height": self.act_rect_h.value(),
            "player": self.act_player.value(),
            "action_index": action_index,
        }
        self.accept()

    def _action_from_form(self):
        kind = ACTION_KINDS[self.act_kind.currentText()]
        if kind == "message":
            return TriggerAction(kind="message", text=self.act_text.text())
        if kind == "createUnit":
            return TriggerAction(kind="createUnit", unit_type=self.act_unit.currentData(),
                                 weapon_type=self.act_weapon.currentData(),
                                 x=self.act_x.value(), y=self.act_y.value(), player=self.act_player.value())
        if kind == "createTrigger":
            target = self.act_target.currentData()
            if not target:
                QMessageBox.information(self, "Kein Ziel", "Es gibt keinen anderen Trigger als Ziel.")
                return None
            return TriggerAction(kind="createTrigger", target=target)
        if kind in ("recordBuilding", "recordTube", "recordWall", "startMiningOperation"):
            group_name = self._selected_building_group()
            if not group_name:
                return None
            if kind == "recordBuilding":
                return TriggerAction(
                    kind="recordBuilding", group_name=group_name,
                    building_type=self.act_building.currentData(),
                    x=self.act_x.value(), y=self.act_y.value())
            if kind == "recordTube":
                return TriggerAction(
                    kind="recordTube", group_name=group_name,
                    x=self.act_x.value(), y=self.act_y.value(),
                    x2=self.act_x2.value(), y2=self.act_y2.value())
            if kind == "recordWall":
                return TriggerAction(
                    kind="recordWall", group_name=group_name,
                    wall_type=self.act_wall.currentData(),
                    x=self.act_x.value(), y=self.act_y.value(),
                    x2=self.act_x2.value(), y2=self.act_y2.value())
            mining_group_name = self._selected_mining_group()
            if not mining_group_name:
                return None
            return TriggerAction(
                kind="startMiningOperation",
                group_name=group_name,
                mining_group_name=mining_group_name,
                ore_type=MINING_OPERATION_ORES[self.act_ore.currentText()],
                truck_count=self.act_truck_count.value(),
                x=self.act_x.value(), y=self.act_y.value(),
                x2=self.act_x2.value(), y2=self.act_y2.value(),
                rect_x=self.act_rect_x.value(), rect_y=self.act_rect_y.value(),
                rect_width=self.act_rect_w.value(), rect_height=self.act_rect_h.value(),
                player=self.act_player.value())
        group_name, source_group_name = self._selected_set_targ_groups()
        if not group_name or not source_group_name:
            return None
        return TriggerAction(
            kind="setTargCount", group_name=group_name,
            source_group_name=source_group_name,
            reinforce_priority=self.act_priority.value(),
            unit_type=self.act_vehicle.currentData(),
            weapon_type="mapNone",
            target_count=self.act_target_count.value())

    def _add_action(self):
        if not (0 <= self._idx < len(self.triggers)):
            return
        a = self._action_from_form()
        if a is None:
            return
        self.triggers[self._idx].actions.append(a)
        self._refresh_actions()
        self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))
        self.alist.setCurrentRow(len(self.triggers[self._idx].actions) - 1)

    def _update_action(self):
        row = self.alist.currentRow()
        if not (0 <= self._idx < len(self.triggers) and 0 <= row < len(self.triggers[self._idx].actions)):
            return
        action = self._action_from_form()
        if action is None:
            return
        self.triggers[self._idx].actions[row] = action
        self._refresh_actions()
        self.alist.setCurrentRow(row)
        self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))

    def _remove_action(self):
        row = self.alist.currentRow()
        if 0 <= self._idx < len(self.triggers) and 0 <= row < len(self.triggers[self._idx].actions):
            del self.triggers[self._idx].actions[row]
            self._refresh_actions()
            self.tlist.item(self._idx).setText(trigger_summary(self.triggers[self._idx]))


class GroupsDialog(QDialog):
    """Gruppen verwalten: MiningGroup, BuildingGroup und ReinforceGroup."""
    def __init__(self, parent, mining_groups, building_groups, reinforce_groups, objects, player_count):
        super().__init__(parent)
        self.setWindowTitle("Gruppen")
        self.resize(880, 560)
        self.groups = (
            [MiningGroupSpec(**asdict(g)) for g in mining_groups] +
            [BuildingGroupSpec(**asdict(g)) for g in building_groups] +
            [
                ReinforceGroupSpec(
                    name=g.name,
                    player=g.player,
                    unit_ids=list(g.unit_ids),
                    targets=[ReinforceTargetSpec(**asdict(t)) for t in g.targets],
                )
                for g in reinforce_groups
            ]
        )
        self.objects = list(objects)
        self._idx = -1
        self._loading = False
        self.rect_pick_request: int | None = None

        self.mines = [o for o in self.objects if o.map_id in ("mapCommonOreMine", "mapRareOreMine")]
        self.smelters = [o for o in self.objects if o.map_id in ("mapCommonOreSmelter", "mapRareOreSmelter")]
        self.trucks = [o for o in self.objects if o.map_id == "mapCargoTruck"]
        self.builders = [
            o for o in self.objects
            if o.map_id in ("mapStructureFactory", "mapVehicleFactory", "mapConVec", "mapEarthworker")
        ]
        self.reinforce_factories = [
            o for o in self.objects
            if o.map_id in ("mapVehicleFactory", "mapArachnidFactory")
        ]

        self.glist = QListWidget()
        self.glist.currentRowChanged.connect(self._on_select)
        add_mining = QPushButton("MiningGroup hinzufuegen"); add_mining.clicked.connect(self._add_mining)
        add_building = QPushButton("BuildingGroup hinzufuegen"); add_building.clicked.connect(self._add_building)
        add_reinforce = QPushButton("ReinforceGroup hinzufuegen"); add_reinforce.clicked.connect(self._add_reinforce)
        rm = QPushButton("Gruppe entfernen"); rm.clicked.connect(self._remove)
        left = QVBoxLayout()
        left.addWidget(QLabel("Gruppen:")); left.addWidget(self.glist, 1)
        left.addWidget(add_mining); left.addWidget(add_building); left.addWidget(add_reinforce); left.addWidget(rm)

        self.name = QLineEdit()
        self.gtype = QComboBox(); self.gtype.addItems(["MiningGroup", "BuildingGroup", "ReinforceGroup"]); self.gtype.setEnabled(False)
        self.player = QSpinBox(); self.player.setRange(0, max(0, player_count - 1))
        self.mine = QComboBox()
        self.smelter = QComboBox()
        self.rect_x = QSpinBox(); self.rect_x.setRange(0, 1023)
        self.rect_y = QSpinBox(); self.rect_y.setRange(0, 1023)
        self.rect_w = QSpinBox(); self.rect_w.setRange(1, 256); self.rect_w.setValue(8)
        self.rect_h = QSpinBox(); self.rect_h.setRange(1, 256); self.rect_h.setValue(8)
        pick_rect = QPushButton("SetRect auf Karte ziehen")
        pick_rect.clicked.connect(self._pick_rect)
        self.pick_rect = pick_rect
        self.unit_list = QListWidget()
        self.target_text = QPlainTextEdit()
        self.target_text.setPlaceholderText("Eine Zielgruppe pro Zeile, z.B.\nCommonMining1=1500\nConstruction=1000")
        self.target_text.setMaximumHeight(120)

        self._fill_object_combo(self.mine, self.mines)
        self._fill_object_combo(self.smelter, self.smelters)

        self.form = QFormLayout()
        self.form.addRow("Name:", self.name)
        self.form.addRow("Typ:", self.gtype)
        self.form.addRow("Spieler:", self.player)
        self.form.addRow("Mine:", self.mine)
        self.form.addRow("Smelter:", self.smelter)
        self.form.addRow("Rect X:", self.rect_x)
        self.form.addRow("Rect Y:", self.rect_y)
        self.form.addRow("Rect Breite:", self.rect_w)
        self.form.addRow("Rect Hoehe:", self.rect_h)
        self.form.addRow("", pick_rect)
        self.form.addRow("Einheiten:", self.unit_list)
        self.form.addRow("Reinforce-Ziele:", self.target_text)

        self.name.textChanged.connect(self._store_current)
        for w in (self.player, self.rect_x, self.rect_y, self.rect_w, self.rect_h):
            w.valueChanged.connect(self._store_current)
        for w in (self.mine, self.smelter):
            w.currentIndexChanged.connect(self._store_current)
        self.unit_list.itemChanged.connect(self._store_current)
        self.target_text.textChanged.connect(self._store_current)

        body = QHBoxLayout(); body.addLayout(left, 1); body.addLayout(self.form, 2)
        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject)
        root = QVBoxLayout(self); root.addLayout(body); root.addWidget(btns)

        self._refresh_list()
        if self.groups:
            self.glist.setCurrentRow(0)
        else:
            self._set_form_enabled(False)

    def mining_groups(self):
        return [g for g in self.groups if isinstance(g, MiningGroupSpec)]

    def building_groups(self):
        return [g for g in self.groups if isinstance(g, BuildingGroupSpec)]

    def reinforce_groups(self):
        return [g for g in self.groups if isinstance(g, ReinforceGroupSpec)]

    def _fill_object_combo(self, combo, objects):
        combo.clear()
        combo.addItem("Leer / spaeter per Trigger", "")
        for o in objects:
            combo.addItem(self._object_label(o), o.uid)

    def _object_label(self, o):
        name = f"{o.unit_name}: " if o.unit_name else ""
        return f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})"

    def _summary(self, group):
        if isinstance(group, MiningGroupSpec):
            return mining_group_summary(group)
        if isinstance(group, ReinforceGroupSpec):
            return reinforce_group_summary(group)
        return building_group_summary(group)

    def _set_form_enabled(self, on):
        for w in (self.name, self.player, self.mine, self.smelter, self.rect_x,
                  self.rect_y, self.rect_w, self.rect_h, self.unit_list, self.target_text):
            w.setEnabled(on)

    def _refresh_list(self):
        self.glist.blockSignals(True)
        cur = self.glist.currentRow()
        self.glist.clear()
        for group in self.groups:
            self.glist.addItem(self._summary(group))
        if 0 <= cur < len(self.groups):
            self.glist.setCurrentRow(cur)
        self.glist.blockSignals(False)

    def _on_select(self, row):
        if not (0 <= row < len(self.groups)):
            self._idx = -1
            self._set_form_enabled(False)
            return
        self._set_form_enabled(True)
        self._idx = row
        self._load(row)

    def _add_mining(self):
        smelter = self.smelters[0] if self.smelters else None
        player = smelter.player if smelter else 0
        rect_x = max(0, smelter.tile_x - 3) if smelter else 0
        rect_y = max(0, smelter.tile_y - 3) if smelter else 0
        group = MiningGroupSpec(
            name=f"MiningGroup{len(self.mining_groups()) + 1}",
            player=player,
            has_setup=False,
            mine_x=0, mine_y=0,
            smelter_x=0, smelter_y=0,
            rect_x=rect_x, rect_y=rect_y,
            rect_width=8, rect_height=8,
            truck_ids=[o.uid for o in self.trucks if o.player == player],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _add_building(self):
        group = BuildingGroupSpec(
            name=f"BuildingGroup{len(self.building_groups()) + 1}",
            player=0,
            rect_x=0, rect_y=0,
            rect_width=8, rect_height=8,
            unit_ids=[o.uid for o in self.builders if o.player == 0],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _add_reinforce(self):
        group = ReinforceGroupSpec(
            name=f"ReinforceGroup{len(self.reinforce_groups()) + 1}",
            player=0,
            unit_ids=[o.uid for o in self.reinforce_factories if o.player == 0],
            targets=[
                ReinforceTargetSpec(group.name, 1500)
                for group in self.mining_groups() + self.building_groups()
            ],
        )
        self.groups.append(group)
        self._refresh_list()
        self.glist.setCurrentRow(len(self.groups) - 1)

    def _remove(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        del self.groups[self._idx]
        self._idx = -1
        self._refresh_list()
        if self.groups:
            self.glist.setCurrentRow(min(self.glist.currentRow(), len(self.groups) - 1))
        else:
            self._set_form_enabled(False)

    def _pick_rect(self):
        if not (0 <= self._idx < len(self.groups)):
            return
        self._store_current()
        self.rect_pick_request = self._idx
        self.accept()

    def _load(self, i):
        group = self.groups[i]
        is_mining = isinstance(group, MiningGroupSpec)
        is_reinforce = isinstance(group, ReinforceGroupSpec)
        self._loading = True
        self.name.setText(group.name)
        if is_mining:
            self.gtype.setCurrentText("MiningGroup")
        elif is_reinforce:
            self.gtype.setCurrentText("ReinforceGroup")
        else:
            self.gtype.setCurrentText("BuildingGroup")
        self.player.setValue(group.player)
        self.form.setRowVisible(self.mine, is_mining)
        self.form.setRowVisible(self.smelter, is_mining)
        for widget in (self.rect_x, self.rect_y, self.rect_w, self.rect_h, self.pick_rect):
            self.form.setRowVisible(widget, not is_reinforce)
        self.form.setRowVisible(self.target_text, is_reinforce)
        if is_mining:
            self._select_combo_by_pos(self.mine, self.mines, group.mine_x, group.mine_y)
            self._select_combo_by_pos(self.smelter, self.smelters, group.smelter_x, group.smelter_y)
            if not getattr(group, "has_setup", True):
                self.mine.setCurrentIndex(0)
                self.smelter.setCurrentIndex(0)
        if not is_reinforce:
            self.rect_x.setValue(group.rect_x)
            self.rect_y.setValue(group.rect_y)
            self.rect_w.setValue(group.rect_width)
            self.rect_h.setValue(group.rect_height)
        else:
            self.target_text.setPlainText(self._targets_to_text(group.targets))
        self._refresh_units(group)
        self._loading = False

    def _select_combo_by_pos(self, combo, objects, x, y):
        for i, o in enumerate(objects, start=1):
            if o.tile_x == x and o.tile_y == y:
                combo.setCurrentIndex(i)
                return
        combo.setCurrentIndex(0)

    def _refresh_units(self, group):
        self.unit_list.blockSignals(True)
        self.unit_list.clear()
        if isinstance(group, MiningGroupSpec):
            objects = self.trucks
            selected = set(group.truck_ids)
        elif isinstance(group, ReinforceGroupSpec):
            objects = self.reinforce_factories
            selected = set(group.unit_ids)
        else:
            objects = self.builders
            selected = set(group.unit_ids)
        for o in objects:
            item = QListWidgetItem(self._object_label(o))
            item.setData(Qt.UserRole, o.uid)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if o.uid in selected else Qt.Unchecked)
            self.unit_list.addItem(item)
        self.unit_list.blockSignals(False)

    def _store_current(self):
        if self._loading or not (0 <= self._idx < len(self.groups)):
            return
        group = self.groups[self._idx]
        if isinstance(group, MiningGroupSpec):
            fallback = "MiningGroup"
        elif isinstance(group, ReinforceGroupSpec):
            fallback = "ReinforceGroup"
        else:
            fallback = "BuildingGroup"
        group.name = self.name.text().strip() or f"{fallback}{self._idx + 1}"
        group.player = self.player.value()
        if isinstance(group, MiningGroupSpec):
            mine = self._object_by_uid(self.mine.currentData())
            smelter = self._object_by_uid(self.smelter.currentData())
            group.has_setup = bool(mine and smelter)
            if mine:
                group.mine_x, group.mine_y = mine.tile_x, mine.tile_y
            if smelter:
                group.smelter_x, group.smelter_y = smelter.tile_x, smelter.tile_y
        if not isinstance(group, ReinforceGroupSpec):
            group.rect_x = self.rect_x.value()
            group.rect_y = self.rect_y.value()
            group.rect_width = self.rect_w.value()
            group.rect_height = self.rect_h.value()
        selected = []
        for i in range(self.unit_list.count()):
            item = self.unit_list.item(i)
            if item.checkState() == Qt.Checked:
                selected.append(item.data(Qt.UserRole))
        if isinstance(group, MiningGroupSpec):
            group.truck_ids = selected
        else:
            group.unit_ids = selected
        if isinstance(group, ReinforceGroupSpec):
            group.targets = self._targets_from_text(self.target_text.toPlainText())
        item = self.glist.item(self._idx)
        if item:
            item.setText(self._summary(group))

    def _targets_to_text(self, targets):
        return "\n".join(f"{target.group_name}={target.priority}" for target in targets)

    def _targets_from_text(self, text):
        targets = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if "=" in line:
                name, priority_text = line.split("=", 1)
            elif ":" in line:
                name, priority_text = line.split(":", 1)
            else:
                name, priority_text = line, "1000"
            name = name.strip()
            if not name:
                continue
            try:
                priority = int(priority_text.strip())
            except ValueError:
                priority = 1000
            targets.append(ReinforceTargetSpec(name, priority))
        return targets

    def _object_by_uid(self, uid):
        for o in self.objects:
            if o.uid == uid:
                return o
        return None


class BuildWorker(QThread):
    ok = Signal(str)
    err = Signal(str)

    def __init__(self, mission):
        super().__init__()
        self.mission = mission

    def run(self):
        try:
            build_mod.write_levelmain(generate_levelmain(self.mission))
            self.ok.emit(str(build_mod.build()))
        except SystemExit as e:
            self.err.emit(str(e))
        except Exception:
            self.err.emit(traceback.format_exc())


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OP2 Mission Editor (Prototyp)")
        self.resize(1250, 870)

        self.vol = VolFile(MAPS_VOL)
        self.map = None
        self.map_name = "cm02.map"
        self.mission_name = "Editor Mission"
        self.players: list[PlayerSpec] = [PlayerSpec()]
        self.objects: list[PlacedObject] = []
        self.victories: list[Condition] = [
            Condition(kind="time", marks=600, objective="Halte 600 Marks durch.")]
        self.defeats: list[Condition] = [Condition(kind="noCC", player=0)]
        self.triggers: list[TriggerDef] = []
        self.groups: list[MiningGroupSpec] = []
        self.building_groups: list[BuildingGroupSpec] = []
        self.reinforce_groups: list[ReinforceGroupSpec] = []
        self._next_object_id = 1
        self._pending_trigger_index = 0
        self._pending_action_index = -1

        cfg = self._load_config()
        self.output_dir = cfg.get("output_dir", DEFAULT_OUTPUT_DIR)
        self.dll_name = cfg.get("dll_name", DEFAULT_DLL_NAME)
        self._placement_active = False
        self._placement_preview_items = []

        self.scene = QGraphicsScene(self)
        self.view = MapView(self.scene)
        self.view.tileClicked.connect(self.on_place)
        self.view.tileRemoved.connect(self.on_remove)
        self.view.tileHover.connect(self._on_tile_hover)
        self.view.rectDragStarted.connect(self._rect_drag_start)
        self.view.rectDragMoved.connect(self._rect_drag_move)
        self.view.rectDragFinished.connect(self._rect_drag_finish)
        self.view.rectDragCanceled.connect(self._rect_drag_cancel)
        self.setCentralWidget(self.view)
        self._rect_pick_group = None
        self._rect_pick_start = None
        self._rect_pick_item = None
        self._action_pick = None
        self._action_pick_start = None
        self._action_preview_items = []
        self._planned_items = []

        self._build_menu()
        self._build_sidebar()
        self._refresh_player_range()

        self.coord_label = QLabel("Tile: –")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().showMessage("Bereit.")
        self.load_map(self.map_name)

    def _load_config(self) -> dict:
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_config(self) -> None:
        try:
            CONFIG_PATH.write_text(json.dumps(
                {"output_dir": self.output_dir, "dll_name": self.dll_name}, indent=2),
                encoding="utf-8")
        except Exception:
            pass

    def _build_menu(self):
        m = self.menuBar().addMenu("&Datei")
        a = QAction("Projekt öffnen…", self); a.triggered.connect(self.open_project); m.addAction(a)
        a = QAction("Projekt speichern…", self); a.triggered.connect(self.save_project); m.addAction(a)
        m.addSeparator()
        a = QAction("Karte wählen…", self); a.triggered.connect(self.choose_map); m.addAction(a)
        a = QAction("Ausgabeort der DLL…", self); a.triggered.connect(self.choose_output); m.addAction(a)
        m.addSeparator()
        a = QAction("Beenden", self); a.triggered.connect(self.close); m.addAction(a)
        m2 = self.menuBar().addMenu("&Mission")
        a = QAction("Spieler…", self); a.triggered.connect(self.edit_players); m2.addAction(a)
        a = QAction("Sieg & Niederlage…", self); a.triggered.connect(self.edit_conditions); m2.addAction(a)
        a = QAction("Gruppen...", self); a.triggered.connect(self.edit_groups); m2.addAction(a)
        a = QAction("Trigger…", self); a.triggered.connect(self.edit_triggers); m2.addAction(a)
        a = QAction("Code anzeigen…", self); a.triggered.connect(self.show_code); m2.addAction(a)
        a = QAction("Build → DLL", self); a.triggered.connect(self.do_build); m2.addAction(a)
        a = QAction("Objekte leeren", self); a.triggered.connect(self.clear_objects); m2.addAction(a)

    def _build_sidebar(self):
        dock = QDockWidget("Platzieren", self)
        panel = QWidget()
        lay = QVBoxLayout(panel)

        lay.addWidget(QLabel("Kategorie:"))
        self.cat_combo = QComboBox()
        self.cat_combo.addItems(CATALOG.keys())
        self.cat_combo.currentTextChanged.connect(self._fill_list)
        lay.addWidget(self.cat_combo)

        self.list = QListWidget()
        self.list.currentItemChanged.connect(self._on_place_selection_changed)
        self.list.itemClicked.connect(lambda _item: self._activate_placement())
        lay.addWidget(self.list, 1)

        # Spieler
        self.player_row = QWidget(); pr = QFormLayout(self.player_row); pr.setContentsMargins(0, 0, 0, 0)
        self.player_spin = QSpinBox(); self.player_spin.setRange(0, 5)
        pr.addRow("Spieler:", self.player_spin)
        lay.addWidget(self.player_row)

        self.unit_name_row = QWidget(); nr = QFormLayout(self.unit_name_row); nr.setContentsMargins(0, 0, 0, 0)
        self.unit_name_edit = QLineEdit()
        self.unit_name_edit.setPlaceholderText("optional, z.B. mainSmelter")
        nr.addRow("Unit-Name:", self.unit_name_edit)
        lay.addWidget(self.unit_name_row)

        # Cargo-Truck-Parameter
        self.cargo_row = QWidget(); cr = QFormLayout(self.cargo_row); cr.setContentsMargins(0, 0, 0, 0)
        self.cargo_combo = QComboBox(); self.cargo_combo.addItems(TRUCK_CARGO.keys())
        self.cargo_amount = QSpinBox(); self.cargo_amount.setRange(0, 5000); self.cargo_amount.setValue(1000)
        cr.addRow("Fracht:", self.cargo_combo); cr.addRow("Menge:", self.cargo_amount)
        lay.addWidget(self.cargo_row)

        # ConVec-Bausatz
        self.kit_row = QWidget(); kr = QFormLayout(self.kit_row); kr.setContentsMargins(0, 0, 0, 0)
        self.kit_combo = QComboBox()
        self.kit_combo.addItem("Leer", None)
        for disp, mid, _ in STRUCTURES:
            self.kit_combo.addItem(disp, mid)
        kr.addRow("Bausatz:", self.kit_combo)
        lay.addWidget(self.kit_row)

        # Beacon-Parameter
        self.beacon_row = QWidget(); br = QFormLayout(self.beacon_row); br.setContentsMargins(0, 0, 0, 0)
        self.ore_combo = QComboBox(); self.ore_combo.addItems(ORE_TYPES.keys())
        self.yield_combo = QComboBox(); self.yield_combo.addItems(YIELDS.keys())
        br.addRow("Erz-Typ:", self.ore_combo); br.addRow("Ertrag:", self.yield_combo)
        lay.addWidget(self.beacon_row)

        lay.addWidget(QLabel(
            "Auswahl aktiv: Links setzen · Rechts abwaehlen\n"
            "Ohne Auswahl: Links bearbeiten · Rechts entfernen\n"
            "Mittel-Drag: schwenken · Rad: zoom"))

        dock.setWidget(panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._fill_list(self.cat_combo.currentText())

    def _fill_list(self, category):
        kind, items = CATALOG[category]
        self.list.clear()
        for disp, mid, fp in items:
            it = QListWidgetItem(f"{disp}  ({fp[0]}×{fp[1]})" if fp != (1, 1) else disp)
            it.setData(Qt.UserRole, (kind, disp, mid, fp))
            self.list.addItem(it)
        self.list.setCurrentRow(0)
        self._update_params()

    def _selected(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else None

    def _on_place_selection_changed(self, *_args):
        self._update_params()
        self._activate_placement()

    def _activate_placement(self):
        sel = self._selected()
        if not sel:
            self._placement_active = False
            self._clear_placement_preview()
            return
        self._placement_active = True
        if self._action_pick is None and self._rect_pick_group is None:
            self.view.setCursor(Qt.CrossCursor)
        kind, display, _map_id, _footprint = sel
        if kind in ("structure", "vehicle"):
            self.statusBar().showMessage(f"Platzieren aktiv: {display}. Rechtsklick waehlt ab.")

    def _cancel_placement(self):
        self._placement_active = False
        self._clear_placement_preview()
        if self._action_pick is None and self._rect_pick_group is None:
            self.view.setCursor(Qt.ArrowCursor)
        self.statusBar().showMessage("Platzierauswahl abgewaehlt.")

    def _update_params(self):
        sel = self._selected()
        if not sel:
            self._placement_active = False
            self._clear_placement_preview()
            return
        kind, disp, mid, fp = sel
        is_struct_or_veh = kind in ("structure", "vehicle")
        self.player_row.setVisible(is_struct_or_veh)
        self.unit_name_row.setVisible(is_struct_or_veh)
        self.cargo_row.setVisible(mid == "mapCargoTruck")
        self.kit_row.setVisible(mid == "mapConVec")
        self.beacon_row.setVisible(mid == "mapMiningBeacon")

    # --- Karte ---
    def choose_map(self):
        dlg = MapDialog(self, self.vol.names(), self.map_name, self.mission_name)
        if dlg.exec() == QDialog.Accepted:
            self.mission_name = dlg.name_edit.text().strip() or "Editor Mission"
            self.load_map(dlg.combo.currentText())
            self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}")

    def edit_players(self):
        dlg = PlayersDialog(self, self.players)
        if dlg.exec() == QDialog.Accepted:
            self.players = dlg.players
            self._refresh_player_range()
            self.statusBar().showMessage(f"{len(self.players)} Spieler konfiguriert.")

    def _refresh_player_range(self):
        self.player_spin.setMaximum(max(0, len(self.players) - 1))

    def edit_triggers(self):
        dlg = TriggersDialog(
            self, self.triggers,
            building_groups=self.building_groups,
            target_groups=self.groups + self.building_groups,
            reinforce_groups=self.reinforce_groups,
            mining_groups=self.groups,
            objects=self.objects,
            initial_trigger_index=self._pending_trigger_index,
            initial_action_index=self._pending_action_index,
        )
        self._pending_trigger_index = 0
        self._pending_action_index = -1
        if dlg.exec() == QDialog.Accepted:
            self.triggers = dlg.triggers
            if dlg.map_pick_request is not None:
                self._begin_action_pick(dlg.map_pick_request)
            else:
                self._redraw_planned_actions()
                self.statusBar().showMessage(f"{len(self.triggers)} Trigger definiert.")

    def edit_conditions(self):
        dlg = ConditionsDialog(self, self.victories, self.defeats)
        if dlg.exec() == QDialog.Accepted:
            self.victories = dlg.victories
            self.defeats = dlg.defeats
            self.statusBar().showMessage(
                f"Bedingungen: {len(self.victories)} Sieg, {len(self.defeats)} Niederlage.")

    def edit_groups(self):
        dlg = GroupsDialog(
            self, self.groups, self.building_groups, self.reinforce_groups,
            self.objects, len(self.players))
        if dlg.exec() == QDialog.Accepted:
            rect_pick_group = None
            if dlg.rect_pick_request is not None and 0 <= dlg.rect_pick_request < len(dlg.groups):
                rect_pick_group = dlg.groups[dlg.rect_pick_request]
            self.groups = dlg.mining_groups()
            self.building_groups = dlg.building_groups()
            self.reinforce_groups = dlg.reinforce_groups()
            total = len(self.groups) + len(self.building_groups) + len(self.reinforce_groups)
            if rect_pick_group is not None:
                self._begin_rect_pick(rect_pick_group)
            else:
                self.statusBar().showMessage(f"{total} Gruppe(n) definiert.")

    def _begin_rect_pick(self, group):
        self._placement_active = False
        self._clear_placement_preview()
        self._rect_pick_group = group
        self._rect_pick_start = None
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
            self._rect_pick_item = None
        self.view.rect_select_enabled = True
        self.view.setCursor(Qt.CrossCursor)
        self.statusBar().showMessage(f"SetRect fuer {group.name}: Rechteck mit linker Maustaste ziehen.")

    def _end_rect_pick(self):
        self.view.rect_select_enabled = False
        self.view.setCursor(Qt.ArrowCursor)
        self._rect_pick_group = None
        self._rect_pick_start = None
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
            self._rect_pick_item = None

    def _rect_from_tiles(self, x1, y1, x2, y2):
        if self.map is None:
            return 0, 0, 1, 1
        left = max(0, min(x1, x2, self.map.width - 1))
        right = max(0, min(max(x1, x2), self.map.width - 1))
        top = max(0, min(y1, y2, self.map.height - 1))
        bottom = max(0, min(max(y1, y2), self.map.height - 1))
        return left, top, right - left + 1, bottom - top + 1

    def _clamp_tile(self, tx, ty):
        if self.map is None:
            return tx, ty
        return (
            max(0, min(tx, self.map.width - 1)),
            max(0, min(ty, self.map.height - 1)),
        )

    def _clear_placement_preview(self):
        for item in self._placement_preview_items:
            self.scene.removeItem(item)
        self._placement_preview_items = []

    def _draw_placement_preview(self, tx, ty):
        self._clear_placement_preview()
        if not self._placement_active:
            return
        sel = self._selected()
        if not sel:
            return
        kind, display, _map_id, footprint = sel
        if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        color = WALL_COLOR
        if kind == "beacon":
            color = BEACON_COLOR
        elif kind in ("structure", "vehicle"):
            color = PLAYER_COLORS[self.player_spin.value() % len(PLAYER_COLORS)]
        footprint_w, footprint_h = footprint
        x0 = (tx - footprint_w // 2) * SCENE_TILE
        y0 = (ty - footprint_h // 2) * SCENE_TILE
        rect = QGraphicsRectItem(
            x0, y0, footprint_w * SCENE_TILE, footprint_h * SCENE_TILE)
        rect.setPen(QPen(color, 2, Qt.DashLine))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
        rect.setZValue(1050)
        self.scene.addItem(rect)
        label = QGraphicsSimpleTextItem(display.split()[0][:10])
        label.setBrush(QBrush(Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        label.setZValue(1051)
        self.scene.addItem(label)
        self._placement_preview_items = [rect, label]

    def _update_rect_overlay(self, x, y, w, h):
        if self._rect_pick_item is not None:
            self.scene.removeItem(self._rect_pick_item)
        self._rect_pick_item = QGraphicsRectItem(
            x * SCENE_TILE, y * SCENE_TILE, w * SCENE_TILE, h * SCENE_TILE)
        self._rect_pick_item.setPen(QPen(QColor(255, 255, 255), 3))
        self._rect_pick_item.setBrush(QBrush(QColor(255, 255, 255, 60)))
        self._rect_pick_item.setZValue(1000)
        self.scene.addItem(self._rect_pick_item)

    def _rect_drag_start(self, tx, ty):
        if self._action_pick and self._action_pick["kind"] == "startMiningOperation" and self._action_pick.get("mode") == "rect":
            tx, ty = self._clamp_tile(tx, ty)
            self._action_pick_start = (tx, ty)
            x, y, w, h = self._rect_from_tiles(tx, ty, tx, ty)
            self._update_rect_overlay(x, y, w, h)
            return
        if self._action_pick and self._action_pick["kind"] in ("recordTube", "recordWall"):
            tx, ty = self._clamp_tile(tx, ty)
            self._action_pick_start = (tx, ty)
            color = QColor(120, 220, 255) if self._action_pick["kind"] == "recordTube" else QColor(255, 180, 80)
            self._draw_action_line_preview(tx, ty, tx, ty, color)
            return
        if self._rect_pick_group is None:
            return
        self._rect_pick_start = (tx, ty)
        x, y, w, h = self._rect_from_tiles(tx, ty, tx, ty)
        self._update_rect_overlay(x, y, w, h)

    def _rect_drag_move(self, tx, ty):
        if self._action_pick and self._action_pick["kind"] == "startMiningOperation" and self._action_pick.get("mode") == "rect" and self._action_pick_start is not None:
            sx, sy = self._action_pick_start
            x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
            self._update_rect_overlay(x, y, w, h)
            self.coord_label.setText(f"Smelter-Rect: {x}, {y}, {w}x{h}")
            return
        if self._action_pick and self._action_pick_start is not None:
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            color = QColor(120, 220, 255) if self._action_pick["kind"] == "recordTube" else QColor(255, 180, 80)
            self._draw_action_line_preview(sx, sy, tx, ty, color)
            self.coord_label.setText(f"Linie: ({sx},{sy}) -> ({tx},{ty})")
            return
        if self._rect_pick_group is None or self._rect_pick_start is None:
            return
        sx, sy = self._rect_pick_start
        x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
        self._update_rect_overlay(x, y, w, h)
        self.coord_label.setText(f"SetRect: {x}, {y}, {w}x{h}")

    def _rect_drag_finish(self, tx, ty):
        if self._action_pick and self._action_pick["kind"] == "startMiningOperation" and self._action_pick.get("mode") == "rect":
            if self._action_pick_start is None:
                self._end_action_pick()
                return
            sx, sy = self._action_pick_start
            x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
            action = self._mining_action_from_pick(rect_x=x, rect_y=y, rect_width=w, rect_height=h)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(f"Smelter-Rect gesetzt: ({x},{y}) {w}x{h}.")
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick_start is not None:
            tx, ty = self._clamp_tile(tx, ty)
            sx, sy = self._action_pick_start
            kind = self._action_pick["kind"]
            if kind == "recordTube":
                action = TriggerAction(
                    kind="recordTube", group_name=self._action_pick["group_name"],
                    x=sx, y=sy, x2=tx, y2=ty)
            else:
                action = TriggerAction(
                    kind="recordWall", group_name=self._action_pick["group_name"],
                    wall_type=self._action_pick["wall_type"],
                    x=sx, y=sy, x2=tx, y2=ty)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(f"{action_summary(action)} hinzugefuegt.")
            self._end_action_pick()
            return
        if self._rect_pick_group is None or self._rect_pick_start is None:
            self._end_rect_pick()
            return
        sx, sy = self._rect_pick_start
        x, y, w, h = self._rect_from_tiles(sx, sy, tx, ty)
        self._rect_pick_group.rect_x = x
        self._rect_pick_group.rect_y = y
        self._rect_pick_group.rect_width = w
        self._rect_pick_group.rect_height = h
        name = self._rect_pick_group.name
        self._end_rect_pick()
        self.statusBar().showMessage(f"SetRect fuer {name}: ({x},{y}) {w}x{h}.")
        QTimer.singleShot(0, self.edit_groups)

    def _rect_drag_cancel(self):
        if self._action_pick is not None:
            self._end_action_pick()
            self.statusBar().showMessage("Aktion-Auswahl abgebrochen.")
            return
        if self._rect_pick_group is None:
            return
        self._end_rect_pick()
        self.statusBar().showMessage("SetRect-Auswahl abgebrochen.")

    def _clear_action_preview(self):
        for item in self._action_preview_items:
            self.scene.removeItem(item)
        self._action_preview_items = []

    def _begin_action_pick(self, request):
        self._placement_active = False
        self._clear_placement_preview()
        self._action_pick = request
        self._action_pick_start = None
        self._clear_action_preview()
        if request["kind"] in ("recordTube", "recordWall") or (
            request["kind"] == "startMiningOperation" and request.get("mode") == "rect"):
            self.view.rect_select_enabled = True
        self.view.setCursor(Qt.CrossCursor)
        label = {
            "recordBuilding": "Gebaeude mit Linksklick setzen",
            "recordTube": "Tube-Linie mit linker Maustaste ziehen",
            "recordWall": "Wall-Linie mit linker Maustaste ziehen",
            "startMiningOperation": {
                "mine": "Mine mit Linksklick setzen",
                "smelter": "Smelter mit Linksklick setzen",
                "rect": "Smelter-Rect mit linker Maustaste ziehen",
            }.get(request.get("mode"), "Mining-Operation auf Karte setzen"),
        }[request["kind"]]
        self.statusBar().showMessage(f"{label}. Rechtsklick bricht ab.")

    def _end_action_pick(self, reopen=True):
        self.view.rect_select_enabled = False
        self.view.setCursor(Qt.ArrowCursor)
        self._action_pick = None
        self._action_pick_start = None
        self._clear_action_preview()
        if reopen:
            QTimer.singleShot(0, self.edit_triggers)

    def _on_tile_hover(self, tx, ty):
        self.coord_label.setText(f"Tile: {tx}, {ty}")
        if self._action_pick and self._action_pick["kind"] == "recordBuilding":
            if self.map is not None and 0 <= tx < self.map.width and 0 <= ty < self.map.height:
                self._draw_action_building_preview(tx, ty)
            else:
                self._clear_action_preview()
            self._clear_placement_preview()
        elif self._action_pick and self._action_pick["kind"] == "startMiningOperation":
            if self._action_pick.get("mode") in ("mine", "smelter") and self.map is not None and 0 <= tx < self.map.width and 0 <= ty < self.map.height:
                self._draw_mining_operation_preview(tx, ty)
            elif self._action_pick.get("mode") != "rect":
                self._clear_action_preview()
            self._clear_placement_preview()
        elif self._placement_active:
            self._draw_placement_preview(tx, ty)
        else:
            self._clear_placement_preview()

    def _draw_action_building_preview(self, tx, ty):
        self._clear_action_preview()
        building_type = self._action_pick["building_type"]
        fw, fh = STRUCTURE_FOOTPRINTS.get(building_type, (1, 1))
        x0 = (tx - fw // 2) * SCENE_TILE
        y0 = (ty - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0, y0, fw * SCENE_TILE, fh * SCENE_TILE)
        rect.setPen(QPen(QColor(255, 255, 255), 3, Qt.DashLine))
        rect.setBrush(QBrush(QColor(255, 255, 255, 45)))
        rect.setZValue(1100)
        self.scene.addItem(rect)
        self._action_preview_items = [rect]

    def _draw_mining_operation_preview(self, tx, ty):
        self._clear_action_preview()
        mode = self._action_pick.get("mode")
        if mode not in ("mine", "smelter"):
            return
        mine_type, smelter_type = MINING_OPERATION_TYPES.get(
            self._action_pick.get("ore_type", "common"), MINING_OPERATION_TYPES["common"])
        building_type = mine_type if mode == "mine" else smelter_type
        fw, fh = STRUCTURE_FOOTPRINTS.get(building_type, (1, 1))
        color = QColor(255, 220, 80) if mode == "mine" else QColor(160, 255, 160)
        x0 = (tx - fw // 2) * SCENE_TILE
        y0 = (ty - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0, y0, fw * SCENE_TILE, fh * SCENE_TILE)
        rect.setPen(QPen(color, 3, Qt.DashLine))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
        rect.setZValue(1100)
        self.scene.addItem(rect)
        self._action_preview_items = [rect]

    def _line_tiles(self, x1, y1, x2, y2):
        tiles = []
        if abs(x2 - x1) >= abs(y2 - y1):
            step = 1 if x2 >= x1 else -1
            for x in range(x1, x2 + step, step):
                tiles.append((x, y1))
            if y2 != y1:
                step_y = 1 if y2 >= y1 else -1
                for y in range(y1 + step_y, y2 + step_y, step_y):
                    tiles.append((x2, y))
        else:
            step = 1 if y2 >= y1 else -1
            for y in range(y1, y2 + step, step):
                tiles.append((x1, y))
            if x2 != x1:
                step_x = 1 if x2 >= x1 else -1
                for x in range(x1 + step_x, x2 + step_x, step_x):
                    tiles.append((x, y2))
        return tiles

    def _draw_action_line_preview(self, x1, y1, x2, y2, color):
        self._clear_action_preview()
        for tx, ty in self._line_tiles(x1, y1, x2, y2):
            rect = QGraphicsRectItem(tx * SCENE_TILE, ty * SCENE_TILE, SCENE_TILE, SCENE_TILE)
            rect.setPen(QPen(color, 2, Qt.DashLine))
            rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 55)))
            rect.setZValue(1100)
            self.scene.addItem(rect)
            self._action_preview_items.append(rect)

    def _mining_action_from_pick(self, **overrides):
        data = dict(self._action_pick)
        data.update(overrides)
        return TriggerAction(
            kind="startMiningOperation",
            group_name=data.get("group_name", ""),
            mining_group_name=data.get("mining_group_name", ""),
            ore_type=data.get("ore_type", "common"),
            truck_count=data.get("truck_count", 0),
            x=data.get("x", 0), y=data.get("y", 0),
            x2=data.get("x2", 0), y2=data.get("y2", 0),
            rect_x=data.get("rect_x", 0), rect_y=data.get("rect_y", 0),
            rect_width=data.get("rect_width", 1), rect_height=data.get("rect_height", 1),
            player=data.get("player", 0),
        )

    def _add_action_from_pick(self, action):
        idx = self._action_pick["trigger_index"]
        if 0 <= idx < len(self.triggers):
            action_index = self._action_pick.get("action_index", -1)
            actions = self.triggers[idx].actions
            if 0 <= action_index < len(actions) and actions[action_index].kind == action.kind:
                actions[action_index] = action
            else:
                actions.append(action)
                action_index = len(actions) - 1
            self._pending_trigger_index = idx
            self._pending_action_index = action_index
        self._redraw_planned_actions()

    def _clear_planned_actions(self):
        for item in self._planned_items:
            self.scene.removeItem(item)
        self._planned_items = []

    def _add_planned_rect(self, x, y, w, h, color, brush_style=Qt.BDiagPattern):
        rect = QGraphicsRectItem(x * SCENE_TILE, y * SCENE_TILE, w * SCENE_TILE, h * SCENE_TILE)
        rect.setPen(QPen(color, 2, Qt.DashLine))
        brush = QBrush(QColor(color.red(), color.green(), color.blue(), 80))
        brush.setStyle(brush_style)
        rect.setBrush(brush)
        rect.setZValue(900)
        self.scene.addItem(rect)
        self._planned_items.append(rect)

    def _add_planned_building(self, x, y, building_type, color):
        fw, fh = STRUCTURE_FOOTPRINTS.get(building_type, (1, 1))
        self._add_planned_rect(x - fw // 2, y - fh // 2, fw, fh, color)

    def _redraw_planned_actions(self):
        self._clear_planned_actions()
        for trigger in self.triggers:
            for action in trigger.actions:
                if action.kind == "recordBuilding":
                    fw, fh = STRUCTURE_FOOTPRINTS.get(action.building_type, (1, 1))
                    self._add_planned_rect(
                        action.x - fw // 2, action.y - fh // 2,
                        fw, fh, QColor(255, 120, 255))
                elif action.kind == "recordTube":
                    for tx, ty in self._line_tiles(action.x, action.y, action.x2, action.y2):
                        self._add_planned_rect(tx, ty, 1, 1, QColor(120, 220, 255), Qt.Dense4Pattern)
                elif action.kind == "recordWall":
                    for tx, ty in self._line_tiles(action.x, action.y, action.x2, action.y2):
                        self._add_planned_rect(tx, ty, 1, 1, QColor(255, 180, 80), Qt.Dense4Pattern)
                elif action.kind == "startMiningOperation":
                    mine_type, smelter_type = MINING_OPERATION_TYPES.get(
                        action.ore_type, MINING_OPERATION_TYPES["common"])
                    self._add_planned_building(action.x, action.y, mine_type, QColor(255, 220, 80))
                    self._add_planned_building(action.x2, action.y2, smelter_type, QColor(160, 255, 160))
                    self._add_planned_rect(
                        action.rect_x, action.rect_y,
                        action.rect_width, action.rect_height,
                        QColor(80, 255, 160), Qt.Dense5Pattern)

    def choose_output(self):
        dlg = OutputDialog(self, self.output_dir, self.dll_name)
        if dlg.exec() == QDialog.Accepted:
            name = dlg.name_edit.text().strip() or DEFAULT_DLL_NAME
            if not name.lower().endswith(".dll"):
                name += ".dll"
            self.output_dir = dlg.dir_edit.text().strip() or DEFAULT_OUTPUT_DIR
            self.dll_name = name
            self._save_config()
            self.statusBar().showMessage(f"Ausgabeort: {Path(self.output_dir) / self.dll_name}")

    def _missions_dir(self) -> Path:
        d = ROOT / "missions"
        d.mkdir(exist_ok=True)
        return d

    def _new_object_uid(self) -> str:
        while True:
            uid = f"obj{self._next_object_id}"
            self._next_object_id += 1
            if all(o.uid != uid for o in self.objects):
                return uid

    def save_project(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Mission speichern", str(self._missions_dir() / "mission.op2proj"),
            "OP2 Mission (*.op2proj);;JSON (*.json)")
        if not path:
            return
        data = {"mission_name": self.mission_name, "map": self.map_name,
                "players": [asdict(p) for p in self.players],
                "objects": [o.to_dict() for o in self.objects],
                "groups": [asdict(g) for g in self.groups],
                "building_groups": [asdict(g) for g in self.building_groups],
                "reinforce_groups": [asdict(g) for g in self.reinforce_groups],
                "triggers": [asdict(t) for t in self.triggers],
                "victories": [asdict(c) for c in self.victories],
                "defeats": [asdict(c) for c in self.defeats]}
        try:
            Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        except Exception as e:
            QMessageBox.critical(self, "Speichern fehlgeschlagen", str(e))
            return
        self.statusBar().showMessage(f"Gespeichert: {path} ({len(self.objects)} Objekte)")

    def open_project(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Mission öffnen", str(self._missions_dir()),
            "OP2 Mission (*.op2proj);;JSON (*.json);;Alle (*.*)")
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as e:
            QMessageBox.critical(self, "Öffnen fehlgeschlagen", str(e))
            return
        self.mission_name = data.get("mission_name", "Editor Mission")
        if "players" in data and data["players"]:
            self.players = []
            for d in data["players"]:
                d = dict(d)
                d["colony"] = Colony(d.get("colony", 0))
                self.players.append(PlayerSpec(**d))
            self._refresh_player_range()
        if "victories" in data:
            self.victories = [Condition(**d) for d in data["victories"]]
        if "defeats" in data:
            self.defeats = [Condition(**d) for d in data["defeats"]]
        if "triggers" in data:
            self.triggers = []
            for td in data["triggers"]:
                try:
                    td = dict(td)
                    actions = [TriggerAction(**a) for a in td.pop("actions", [])]
                    self.triggers.append(TriggerDef(actions=actions, **td))
                except Exception:
                    continue
        self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}")
        self.load_map(data.get("map", self.map_name))  # leert Szene + Objekte
        used_uids = {d.get("uid") for d in data.get("objects", []) if d.get("uid")}
        for od in data.get("objects", []):
            try:
                obj = PlacedObject.from_dict(od)
            except Exception:
                continue
            if not obj.uid:
                while True:
                    obj.uid = self._new_object_uid()
                    if obj.uid not in used_uids:
                        used_uids.add(obj.uid)
                        break
            self._draw(obj)
            self.objects.append(obj)
        self.groups = []
        for gd in data.get("groups", []):
            try:
                self.groups.append(MiningGroupSpec(**gd))
            except Exception:
                continue
        self.building_groups = []
        for gd in data.get("building_groups", []):
            try:
                self.building_groups.append(BuildingGroupSpec(**gd))
            except Exception:
                continue
        self.reinforce_groups = []
        for gd in data.get("reinforce_groups", []):
            try:
                gd = dict(gd)
                targets = [
                    ReinforceTargetSpec(**target)
                    for target in gd.pop("targets", [])
                ]
                self.reinforce_groups.append(ReinforceGroupSpec(targets=targets, **gd))
            except Exception:
                continue
        self._redraw_planned_actions()
        self.statusBar().showMessage(
            f"Geladen: {path} ({len(self.objects)} Objekte, "
            f"{len(self.groups) + len(self.building_groups) + len(self.reinforce_groups)} Gruppe(n))")

    def load_map(self, name):
        try:
            self.map = Op2Map(self.vol.read_file(name))
            arr = np.ascontiguousarray(render_array(self.map, self.vol))
            qimg = QImage(arr.data, arr.shape[1], arr.shape[0], arr.shape[1] * 3, QImage.Format_RGB888)
            pix = QPixmap.fromImage(qimg.copy())
        except Exception as e:
            QMessageBox.critical(self, "Fehler", f"{e}\n\n{traceback.format_exc()}")
            return
        self.map_name = name
        self.objects.clear()
        self.groups.clear()
        self.building_groups.clear()
        self.reinforce_groups.clear()
        self._next_object_id = 1
        self.scene.clear()
        self.view.rect_select_enabled = False
        self._placement_active = False
        self._placement_preview_items = []
        self._rect_pick_group = None
        self._rect_pick_start = None
        self._rect_pick_item = None
        self._action_pick = None
        self._action_pick_start = None
        self._action_preview_items = []
        self._planned_items = []
        self.scene.addPixmap(pix)
        self.scene.setSceneRect(QRectF(pix.rect()))
        self.view.resetTransform()
        self.view.fitInView(self.scene.sceneRect(), Qt.KeepAspectRatio)
        self.statusBar().showMessage(f"{name}: {self.map.width}×{self.map.height} Tiles.")

    # --- Platzieren / Entfernen ---
    def _object_at(self, tx, ty):
        for obj in reversed(self.objects):
            if obj.covers(tx, ty):
                return obj
        return None

    def _redraw_object(self, obj: PlacedObject):
        for item in obj.items:
            self.scene.removeItem(item)
        self._draw(obj)

    def _edit_object_at(self, tx, ty):
        obj = self._object_at(tx, ty)
        if obj is None:
            return
        if obj.kind not in ("structure", "vehicle"):
            self.statusBar().showMessage(f"{obj.display} hat keine Unit-Parameter.")
            return
        dlg = ObjectEditDialog(self, obj, len(self.players))
        if dlg.exec() == QDialog.Accepted:
            dlg.apply_to(obj)
            self._redraw_object(obj)
            label = obj.unit_name or obj.display
            self.statusBar().showMessage(f"{label} aktualisiert.")

    def on_place(self, tx, ty):
        if self._action_pick and self._action_pick["kind"] == "startMiningOperation":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            mode = self._action_pick.get("mode")
            if mode == "mine":
                action = self._mining_action_from_pick(x=tx, y=ty)
                message = f"Mine gesetzt: ({tx},{ty})."
            elif mode == "smelter":
                action = self._mining_action_from_pick(x2=tx, y2=ty)
                message = f"Smelter gesetzt: ({tx},{ty})."
            else:
                return
            self._add_action_from_pick(action)
            self.statusBar().showMessage(message)
            self._end_action_pick()
            return
        if self._action_pick and self._action_pick["kind"] == "recordBuilding":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            action = TriggerAction(
                kind="recordBuilding",
                group_name=self._action_pick["group_name"],
                building_type=self._action_pick["building_type"],
                x=tx, y=ty)
            self._add_action_from_pick(action)
            self.statusBar().showMessage(f"{action_summary(action)} hinzugefuegt.")
            self._end_action_pick()
            return
        if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
            return
        if not self._placement_active:
            self._edit_object_at(tx, ty)
            return
        sel = self._selected()
        if not sel:
            return
        kind, disp, mid, fp = sel
        params = {}
        if mid == "mapCargoTruck":
            params["truck_cargo"] = TRUCK_CARGO[self.cargo_combo.currentText()]
            params["truck_amount"] = self.cargo_amount.value()
        elif mid == "mapConVec":
            convec_kit = self.kit_combo.currentData()
            if convec_kit:
                params["convec_kit"] = convec_kit
        elif mid == "mapMiningBeacon":
            params["ore_type"] = ORE_TYPES[self.ore_combo.currentText()]
            params["yield_bars"] = YIELDS[self.yield_combo.currentText()]
        player = self.player_spin.value() if kind in ("structure", "vehicle") else 0
        unit_name = self.unit_name_edit.text().strip() if kind in ("structure", "vehicle") else ""
        obj = PlacedObject(kind, tx, ty, mid, fp, disp, player, params, self._new_object_uid(), unit_name)
        self._draw(obj)
        self.objects.append(obj)
        label = unit_name or disp
        self.statusBar().showMessage(f"{label} @ ({tx},{ty}). Gesamt: {len(self.objects)}")

    def on_remove(self, tx, ty):
        if self._action_pick is not None:
            self._end_action_pick()
            self.statusBar().showMessage("Aktion-Auswahl abgebrochen.")
            return
        if self._placement_active:
            self._cancel_placement()
            return
        obj = self._object_at(tx, ty)
        if obj is not None:
            for item in obj.items:
                self.scene.removeItem(item)
            self.objects.remove(obj)
            self.statusBar().showMessage(f"{obj.display} entfernt. Gesamt: {len(self.objects)}")

    def _draw(self, obj: PlacedObject):
        if obj.kind == "beacon":
            color = BEACON_COLOR
        elif obj.kind == "wall":
            color = WALL_COLOR
        else:
            color = PLAYER_COLORS[obj.player % len(PLAYER_COLORS)]
        fw, fh = obj.footprint
        x0 = (obj.tile_x - fw // 2) * SCENE_TILE
        y0 = (obj.tile_y - fh // 2) * SCENE_TILE
        rect = QGraphicsRectItem(x0, y0, fw * SCENE_TILE, fh * SCENE_TILE)
        rect.setPen(QPen(color, 2))
        rect.setBrush(QBrush(QColor(color.red(), color.green(), color.blue(), 120)))
        self.scene.addItem(rect)
        text = obj.unit_name or obj.display.split()[0]
        label = QGraphicsSimpleTextItem(text[:10])
        label.setBrush(QBrush(Qt.black if obj.kind == "beacon" else Qt.white))
        label.setPos(x0 + 2, y0 + 1)
        self.scene.addItem(label)
        obj.items = [rect, label]

    def clear_objects(self):
        for obj in self.objects:
            for it in obj.items:
                self.scene.removeItem(it)
        self.objects.clear()
        self.groups.clear()
        self.building_groups.clear()
        self.reinforce_groups.clear()
        self.statusBar().showMessage("Objekte geleert.")

    # --- Build ---
    def build_mission(self) -> Mission:
        # Offset +31/-1 wird im Codegen ergaenzt (MkXY fuer Einheiten, XYPos fuer Beacons/Walls).
        units, beacons, walls = [], [], []
        for o in self.objects:
            if o.kind in ("structure", "vehicle"):
                units.append(UnitSpec(
                    o.map_id, x=o.tile_x, y=o.tile_y, player=o.player,
                    truck_cargo=o.params.get("truck_cargo"),
                    truck_amount=o.params.get("truck_amount", 1000),
                    convec_kit=o.params.get("convec_kit"),
                    uid=o.uid,
                    unit_name=o.unit_name,
                ))
            elif o.kind == "beacon":
                beacons.append(BeaconSpec(
                    o.map_id, x=o.tile_x, y=o.tile_y,
                    ore_type=o.params.get("ore_type", -1),
                    yield_bars=o.params.get("yield_bars", -1),
                ))
            elif o.kind == "wall":
                walls.append(WallTubeSpec(o.map_id, x=o.tile_x, y=o.tile_y))
        return Mission(
            name=self.mission_name, map=self.map_name, type=MissionType.Colony,
            num_players=len(self.players),
            players=[PlayerSpec(**asdict(p)) for p in self.players],
            units=units, beacons=beacons, walls_tubes=walls,
            mining_groups=[MiningGroupSpec(**asdict(g)) for g in self.groups],
            building_groups=[BuildingGroupSpec(**asdict(g)) for g in self.building_groups],
            reinforce_groups=[
                ReinforceGroupSpec(
                    name=g.name,
                    player=g.player,
                    unit_ids=list(g.unit_ids),
                    targets=[ReinforceTargetSpec(**asdict(t)) for t in g.targets],
                )
                for g in self.reinforce_groups
            ],
            triggers=list(self.triggers),
            start_message=StartMessage("Mit dem OP2 Mission Editor erstellt."),
            victories=list(self.victories), defeats=list(self.defeats),
        )

    def show_code(self):
        if self.map is None:
            return
        try:
            code = generate_levelmain(self.build_mission())
        except Exception:
            code = traceback.format_exc()
        dlg = QDialog(self)
        dlg.setWindowTitle("Generierter C++-Code (LevelMain.cpp)")
        dlg.resize(760, 640)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(code)
        text.setFont(QFont("Consolas", 10))
        text.setLineWrapMode(QPlainTextEdit.NoWrap)
        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(dlg.reject)
        btns.accepted.connect(dlg.accept)
        lay = QVBoxLayout(dlg)
        lay.addWidget(text)
        lay.addWidget(btns)
        dlg.exec()

    def do_build(self):
        if self.map is None:
            return
        self._progress = QProgressDialog("Build läuft… (C++ wird kompiliert)", None, 0, 0, self)
        self._progress.setWindowTitle("Build")
        self._progress.setWindowModality(Qt.WindowModal)
        self._progress.setCancelButton(None)
        self._progress.show()
        self.statusBar().showMessage("Build läuft…")
        self._worker = BuildWorker(self.build_mission())
        self._worker.ok.connect(self._build_ok)
        self._worker.err.connect(self._build_err)
        self._worker.start()

    def _build_ok(self, dll):
        self._progress.close()
        target = Path(self.output_dir) / self.dll_name
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(dll, target)
        except Exception as e:
            QMessageBox.warning(self, "Kopieren fehlgeschlagen",
                                f"Build OK, aber Kopieren nach\n{target}\nschlug fehl:\n{e}")
            self.statusBar().showMessage(f"Build OK, Kopieren fehlgeschlagen: {e}")
            return
        self.statusBar().showMessage(f"Build OK → {target}")
        QMessageBox.information(self, "Build erfolgreich",
                                f"Mission gebaut ({len(self.objects)} Objekte) und kopiert nach:\n{target}")

    def _build_err(self, msg):
        self._progress.close()
        self.statusBar().showMessage("Build fehlgeschlagen.")
        QMessageBox.critical(self, "Build fehlgeschlagen", msg)


def main():
    app = QApplication(sys.argv)
    win = EditorWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
