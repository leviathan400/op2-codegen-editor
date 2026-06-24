"""Mission-Modell: die sprachunabhaengige Beschreibung einer Outpost-2-Mission.

Das ist das Herzstueck. Eine GUI wuerde spaeter genau diese Objekte
befuellen; der Codegen (codegen.py) liest sie und erzeugt LevelMain.cpp.
Hier wird absichtlich KEIN C++ erwaehnt -- reine Daten.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class MissionType(IntEnum):
    """Entspricht MissionTypes in RequiredExports.h."""
    Colony = -1
    AutoDemo = -2
    Tutorial = -3
    MultiLandRush = -4
    MultiSpaceRace = -5
    MultiResourceRace = -6
    MultiMidas = -7
    MultiLastOneStanding = -8


class Colony(IntEnum):
    Eden = 0
    Plymouth = 1


@dataclass
class PlayerSpec:
    """Konfiguration eines Spielers."""
    colony: Colony = Colony.Eden
    is_human: bool = True          # True -> GoHuman, False -> GoAI
    tech_level: int = 12           # 12 = alle Technologien (SetTechLevel)
    init_resources: bool = True    # Startressourcen via OP2Helper setzen
    # Kolonisten (None = nicht explizit setzen)
    kids: int | None = None
    workers: int | None = None
    scientists: int | None = None
    # Ressourcen (None = nicht explizit setzen)
    common_ore: int | None = None
    rare_ore: int | None = None
    food: int | None = None
    # Einzelne Vorab-Forschungen (Tech-IDs) zusaetzlich zu tech_level
    researches: list[int] = field(default_factory=list)


@dataclass
class UnitSpec:
    """Eine zu platzierende Einheit/Gebaeude.

    `unit_type` ist eine map_id (z.B. "mapCommandCenter"), Koordinaten
    sind 0-basierte Editor-Tile-Koordinaten. Der Codegen wandelt sie vor
    MkXY/XYPos/MkRect auf die 1-basierten OP2-Koordinaten um.
    """
    unit_type: str
    x: int
    y: int
    player: int = 0
    cargo: str = "mapNone"   # weaponCargoType bei CreateUnit
    rotation: int = 0
    truck_cargo: str | None = None   # Cargo Truck: SetTruckCargo(truck_cargo, truck_amount)
    truck_amount: int = 1000
    convec_kit: str | None = None    # ConVec: SetCargo(convec_kit, mapNone) -- Gebaeude-Bausatz
    uid: str = ""                    # Editor-interne ID fuer Gruppenreferenzen
    unit_name: str = ""              # Optionaler ScriptGlobal-Name fuer Zugriff nach Save/Load


def action_from_dict(d: dict) -> "TriggerAction":
    """Baut eine TriggerAction rekursiv aus einem Dict (inkl. Bedingungen + then/else)."""
    d = dict(d)
    conds = [ActionCondition(**c) for c in d.pop("conditions", [])]
    then = [action_from_dict(a) for a in d.pop("then_actions", [])]
    els = [action_from_dict(a) for a in d.pop("else_actions", [])]
    return TriggerAction(conditions=conds, then_actions=then, else_actions=els, **d)


@dataclass
class BeaconSpec:
    """Mining Beacon / Magma Vent / Fumarole (Geysir)."""
    beacon_type: str          # mapMiningBeacon / mapMagmaVent / mapFumarole
    x: int
    y: int
    ore_type: int = -1        # -1 zufaellig, 0 common, 1 rare (nur Mining Beacon)
    yield_bars: int = -1      # -1 zufaellig, 0=Bar3, 1=Bar2, 2=Bar1
    variant: int = -1         # -1 zufaellig, 0..2


@dataclass
class WallTubeSpec:
    """Mauer oder Rohr (einzelne Kachel)."""
    wall_type: str            # mapTube / mapWall / mapLavaWall / mapMicrobeWall
    x: int
    y: int


@dataclass
class MiningGroupSpec:
    """MiningGroup: Mine, Smelter-Bereich und optionale Cargo Trucks."""
    name: str
    player: int = 0
    has_setup: bool = True
    mine_x: int = 0
    mine_y: int = 0
    smelter_x: int = 0
    smelter_y: int = 0
    rect_x: int = 0
    rect_y: int = 0
    rect_width: int = 4
    rect_height: int = 4
    truck_ids: list[str] = field(default_factory=list)


@dataclass
class BuildingGroupSpec:
    """BuildingGroup: Builder-Einheiten und Standardbereich."""
    name: str
    player: int = 0
    rect_x: int = 0
    rect_y: int = 0
    rect_width: int = 8
    rect_height: int = 8
    unit_ids: list[str] = field(default_factory=list)


@dataclass
class ReinforceTargetSpec:
    """Zielgruppe, die von einer ReinforceGroup Fahrzeuge anfordern darf."""
    group_name: str
    priority: int = 1000


@dataclass
class ReinforceGroupSpec:
    """ReinforceGroup: BuildingGroup mit Vehicle-Factories fuer Fahrzeugnachschub."""
    name: str
    player: int = 0
    unit_ids: list[str] = field(default_factory=list)
    targets: list[ReinforceTargetSpec] = field(default_factory=list)


@dataclass
class ActionCondition:
    """Eine IF-Bedingung, die eine einzelne Aktion gated (Home-Assistant-Stil).

    kind: buildingAtLocation | unitDamage | playerResource | buildingCount | hasTech
    """
    kind: str
    negate: bool = False
    player: int = 0
    building_type: str = "mapCommandCenter"
    x: int = 0
    y: int = 0
    compare: str = "cmpGreaterEqual"
    value: int = 0
    resource: str = "resCommonOre"
    tech_id: int = 0


@dataclass
class TriggerAction:
    """Eine Aktion in der Callback-Funktion eines Triggers."""
    kind: str                 # "message" | "createUnit" | "createTrigger" | "recordBuilding" | "recordTube" | "recordWall" | "setTargCount" | "startMiningOperation"
    text: str = ""            # message
    unit_type: str = "mapScout"   # createUnit
    weapon_type: str = "mapNone"  # createUnit / SetTargCount
    target_count: int = 1      # SetTargCount
    x: int = 0
    y: int = 0
    x2: int = 0
    y2: int = 0
    rect_x: int = 0
    rect_y: int = 0
    rect_width: int = 8
    rect_height: int = 8
    player: int = 0
    target: str = ""          # createTrigger -> Name eines anderen Triggers (Laufzeit-Erstellung)
    group_name: str = ""      # BuildingGroup-Aktionen
    mining_group_name: str = ""  # MiningGroup fuer StartMiningOperation
    source_group_name: str = ""  # ReinforceGroup, die SetTargCount-Zielgruppe beliefert
    reinforce_priority: int = 1000
    ore_type: str = "common"
    truck_count: int = 0      # StartMiningOperation: Ziel-Anzahl Transporter (0 = automatisch)
    truck_ids: list[str] = field(default_factory=list)
    building_type: str = "mapCommandCenter"
    wall_type: str = "mapWall"
    # IF-Bedingungen: Aktion laeuft nur, wenn erfuellt (UND/ODER verknuepft).
    # Bei kind == "if" sind dies die "Wenn"-Bedingungen des Blocks.
    conditions: list["ActionCondition"] = field(default_factory=list)
    condition_logic: str = "and"   # "and" | "or"
    # Nur fuer kind == "if": verschachtelte Aktionen (rekursiv).
    then_actions: list["TriggerAction"] = field(default_factory=list)  # Dann
    else_actions: list["TriggerAction"] = field(default_factory=list)  # Sonst


@dataclass
class TriggerDef:
    """Ein benutzerdefinierter Trigger: Bedingung + Aktionen.

    `enabled_at_start`: True -> wird in InitProc erzeugt; False -> entsteht nur,
    wenn ein anderer Trigger ihn per createTrigger-Aktion erstellt (Laufzeit).
    `condition` waehlt die OP2-Trigger-Funktion; genutzte Felder je condition:
      time          -> marks
      point         -> player, x, y
      rect          -> player, x, y, width, height
      buildingCount -> player, count, compare
      vehicleCount  -> player, count, compare
      research      -> player, tech_id
      resource      -> player, resource, amount, compare
      operational   -> player, building, count, compare
    """
    name: str
    enabled_at_start: bool = True
    one_shot: bool = True
    condition: str = "time"
    marks: int = 100
    player: int = 0
    count: int = 1
    compare: str = "cmpGreaterEqual"
    tech_id: int = 0
    resource: str = "resCommonOre"
    amount: int = 1000
    building: str = "mapCommandCenter"
    x: int = 0
    y: int = 0
    width: int = 1
    height: int = 1
    actions: list[TriggerAction] = field(default_factory=list)


@dataclass
class StartMessage:
    """Nachricht, die zu Spielbeginn allen Spielern angezeigt wird."""
    text: str


@dataclass
class Condition:
    """Eine Sieg- oder Niederlage-Bedingung.

    `kind` waehlt die OP2-Trigger-/Helper-Funktion; je nach kind werden nur
    bestimmte Felder verwendet:
      time          -> marks, objective
      lastStanding  -> (Helper, Sieg)
      starship      -> (Helper, Sieg)
      noCC          -> player (Helper, Niederlage)
      buildingCount -> player, count, compare, objective
      vehicleCount  -> player, count, compare, objective
      research      -> player, tech_id, objective
      resource      -> player, resource, amount, compare, objective
      operational   -> player, building, count, compare, objective
    """
    kind: str
    objective: str = ""
    player: int = 0
    marks: int = 600
    count: int = 1
    compare: str = "cmpGreaterEqual"
    tech_id: int = 0
    resource: str = "resCommonOre"
    amount: int = 1000
    building: str = "mapCommandCenter"


@dataclass
class Mission:
    """Vollstaendige Missionsbeschreibung -- der Wurzelknoten des Modells."""
    name: str
    map: str
    tech_tree: str = "MULTITEK.TXT"
    type: MissionType = MissionType.Colony
    num_players: int = 1

    players: list[PlayerSpec] = field(default_factory=lambda: [PlayerSpec()])
    units: list[UnitSpec] = field(default_factory=list)
    beacons: list[BeaconSpec] = field(default_factory=list)
    walls_tubes: list[WallTubeSpec] = field(default_factory=list)
    mining_groups: list[MiningGroupSpec] = field(default_factory=list)
    building_groups: list[BuildingGroupSpec] = field(default_factory=list)
    reinforce_groups: list[ReinforceGroupSpec] = field(default_factory=list)
    triggers: list[TriggerDef] = field(default_factory=list)
    start_message: StartMessage | None = None
    victories: list[Condition] = field(default_factory=list)
    defeats: list[Condition] = field(default_factory=list)
