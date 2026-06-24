from __future__ import annotations
from .common import *
from .placed_object import PlacedObject
from .mapview import MapView
from .build_worker import BuildWorker
from .dialogs.map_dialog import MapDialog
from .dialogs.object_edit import ObjectEditDialog
from .dialogs.output_dialog import OutputDialog
from .dialogs.conditions import ConditionsDialog
from .dialogs.players import PlayersDialog
from .dialogs.triggers import TriggersDialog
from .dialogs.groups import GroupsDialog


class EditorWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OP2 Mission Editor (Prototyp)")
        self.resize(1250, 870)

        try:
            self.res = FolderResources(OP2_DIR)
            if not self.res.names():
                raise FileNotFoundError(f"keine .map-Dateien unter {self.res.root}")
        except Exception as e:
            QMessageBox.critical(
                self, "Outpost 2 nicht gefunden",
                f"Karten konnten nicht geladen werden:\n{e}\n\n"
                f"Bitte 'game_path' in der config.ini anpassen:\n{appconfig.CONFIG_PATH}")
            raise SystemExit(1)
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
        self.node_positions: dict = {}  # Timeline-Knotenpositionen (key -> [x, y])
        self._next_object_id = 1
        self._pending_trigger_index = 0
        self._pending_action_index = -1

        self.output_dir = DEFAULT_OUTPUT_DIR
        self.dll_name = DEFAULT_DLL_NAME
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
        self._build_overview()
        self._refresh_player_range()

        self.coord_label = QLabel("Tile: –")
        self.statusBar().addPermanentWidget(self.coord_label)
        self.statusBar().showMessage("Bereit.")
        self.load_map(self.map_name)
        self._refresh_overview()

    def _build_menu(self):
        m = self.menuBar().addMenu("&Datei")
        a = QAction("Projekt öffnen…", self); a.triggered.connect(self.open_project); m.addAction(a)
        a = QAction("Projekt speichern…", self); a.triggered.connect(self.save_project); m.addAction(a)
        m.addSeparator()
        a = QAction("Karte wählen…", self); a.triggered.connect(self.choose_map); m.addAction(a)
        a = QAction("Ausgabeort der DLL…", self); a.triggered.connect(self.choose_output); m.addAction(a)
        m.addSeparator()
        a = QAction("Beenden", self); a.triggered.connect(self.close); m.addAction(a)

        # "Mission"-Aktionen als obere Werkzeugleiste statt Menue.
        tb = QToolBar("Mission", self)
        tb.setToolButtonStyle(Qt.ToolButtonTextOnly)
        self.addToolBar(tb)
        for label, slot in [
            ("Spieler", self.edit_players),
            ("Sieg & Niederlage", self.edit_conditions),
            ("Gruppen", self.edit_groups),
            ("Trigger", self.edit_triggers),
            ("Code anzeigen", self.show_code),
            ("Build → DLL", self.do_build),
            ("Objekte leeren", self.clear_objects),
        ]:
            act = QAction(label, self)
            act.triggered.connect(slot)
            tb.addAction(act)

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
        self.cargo_combo.setCurrentText("Leer")  # Trucks standardmaessig leer
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

        # Waffe (Kampffahrzeuge Lynx/Panther/Tiger + Guard Post)
        self.weapon_row = QWidget(); wr = QFormLayout(self.weapon_row); wr.setContentsMargins(0, 0, 0, 0)
        self.weapon_combo = QComboBox()
        for d, m in WEAPONS:
            self.weapon_combo.addItem(d, m)
        wr.addRow("Waffe:", self.weapon_combo)
        lay.addWidget(self.weapon_row)

        lay.addWidget(QLabel(
            "Auswahl aktiv: Links setzen · Rechts abwaehlen\n"
            "Ohne Auswahl: Links bearbeiten · Rechts entfernen\n"
            "Mittel-Drag: schwenken · Rad: zoom"))

        dock.setWidget(panel)
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        self._fill_list(self.cat_combo.currentText())

    # --- Mission-Uebersicht: Ausfuehrungs-Flussbaum + Gesamtuebersicht (Dock rechts) ---
    def _build_overview(self):
        dock = QDockWidget("Mission-Übersicht", self)
        dock.setAllowedAreas(Qt.LeftDockWidgetArea | Qt.RightDockWidgetArea)
        panel = QWidget()
        lay = QVBoxLayout(panel)
        bar = QHBoxLayout()
        add_btn = QPushButton("Trigger +"); add_btn.clicked.connect(self._add_trigger)
        bar.addWidget(add_btn); bar.addStretch(1)
        lay.addLayout(bar)
        self.overview = QTreeWidget()
        self.overview.setHeaderHidden(True)
        self.overview.itemDoubleClicked.connect(self._overview_activated)
        lay.addWidget(self.overview, 1)
        lay.addWidget(QLabel("Doppelklick: bearbeiten · Trigger sind nach Ausführung verschachtelt"))
        dock.setWidget(panel)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def _ov_add(self, parent, text, kind=None, index=None, sub=None):
        item = QTreeWidgetItem([text])
        if kind is not None:
            item.setData(0, Qt.UserRole, (kind, index, sub))
        if isinstance(parent, QTreeWidgetItem):
            parent.addChild(item)
        else:
            parent.addTopLevelItem(item)
        return item

    def _add_trigger(self):
        name = f"Trigger{len(self.triggers) + 1}"
        self.triggers.append(TriggerDef(name=name))
        self._refresh_overview()
        self.statusBar().showMessage(f"Trigger '{name}' angelegt (Doppelklick zum Bearbeiten).")

    def _trigger_cond_text(self, t):
        return {v: k for k, (v, _) in TRIGGER_CONDITIONS.items()}.get(t.condition, t.condition)

    def _add_flow_trigger(self, parent, ti, path, prefix=""):
        t = self.triggers[ti]
        tag = "[Start] " if t.enabled_at_start else ""
        item = self._ov_add(parent, f"{prefix}{tag}{t.name}  ({self._trigger_cond_text(t)})",
                             "triggers", ti)
        new_path = path | {ti}
        for ai, a in enumerate(t.actions):
            if a.kind == "createTrigger" and a.target in self._trig_idx_by_name:
                tgt = self._trig_idx_by_name[a.target]
                if tgt in new_path:
                    self._ov_add(item, f"⟶ {a.target} (siehe oben)", "triggers", tgt)
                else:
                    self._add_flow_trigger(item, tgt, new_path, prefix="⟶ ")
            else:
                self._ov_add(item, "· " + action_summary(a), "triggers", ti, ai)
        return item

    def _refresh_overview(self):
        if not hasattr(self, "overview"):
            return
        expanded = {self.overview.topLevelItem(i).text(0).split(" (")[0]
                    for i in range(self.overview.topLevelItemCount())
                    if self.overview.topLevelItem(i).isExpanded()}
        self.overview.clear()
        self._trig_idx_by_name = {t.name: i for i, t in enumerate(self.triggers)}
        created = {a.target for t in self.triggers for a in t.actions
                   if a.kind == "createTrigger" and a.target}

        sec_flow = self._ov_add(self.overview, f"Ablauf / Trigger ({len(self.triggers)})")
        for i, t in enumerate(self.triggers):
            if t.enabled_at_start:
                self._add_flow_trigger(sec_flow, i, set())
        for i, t in enumerate(self.triggers):
            if not t.enabled_at_start and t.name not in created:
                self._add_flow_trigger(sec_flow, i, set(), prefix="(ungebunden) ")

        sec_players = self._ov_add(self.overview, f"Spieler ({len(self.players)})")
        for i, p in enumerate(self.players):
            colony = "Eden" if p.colony == Colony.Eden else "Plymouth"
            self._ov_add(sec_players,
                         f"Spieler {i} — {colony}, {'Mensch' if p.is_human else 'KI'}, Tech {p.tech_level}",
                         "players", i)

        groups_total = len(self.groups) + len(self.building_groups) + len(self.reinforce_groups)
        sec_groups = self._ov_add(self.overview, f"Gruppen ({groups_total})")
        for g in self.groups:
            self._ov_add(sec_groups, mining_group_summary(g), "groups")
        for g in self.building_groups:
            self._ov_add(sec_groups, building_group_summary(g), "groups")
        for g in self.reinforce_groups:
            self._ov_add(sec_groups, reinforce_group_summary(g), "groups")

        sec_cond = self._ov_add(self.overview,
                                f"Sieg/Niederlage ({len(self.victories)}/{len(self.defeats)})")
        for c in self.victories:
            self._ov_add(sec_cond, f"Sieg: {condition_summary(c)}", "conditions")
        for c in self.defeats:
            self._ov_add(sec_cond, f"Niederlage: {condition_summary(c)}", "conditions")

        sec_obj = self._ov_add(self.overview, f"Objekte ({len(self.objects)})")
        for oi, o in enumerate(self.objects):
            name = f"{o.unit_name}: " if getattr(o, "unit_name", "") else ""
            self._ov_add(sec_obj, f"{name}{o.display} P{o.player} @ ({o.tile_x},{o.tile_y})",
                         "objects", oi)

        for i in range(self.overview.topLevelItemCount()):
            it = self.overview.topLevelItem(i)
            it.setExpanded(not expanded or it.text(0).split(" (")[0] in expanded)
        sec_flow.setExpanded(True)

    def _overview_activated(self, item, _col=0):
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        kind, index, sub = data
        if kind == "players":
            self.edit_players()
        elif kind == "groups":
            self.edit_groups()
        elif kind == "conditions":
            self.edit_conditions()
        elif kind == "triggers":
            self._pending_trigger_index = index if index is not None else 0
            self._pending_action_index = sub if sub is not None else -1
            self.edit_triggers()
        elif kind == "objects" and index is not None and 0 <= index < len(self.objects):
            o = self.objects[index]
            self.view.centerOn(o.tile_x * SCENE_TILE, o.tile_y * SCENE_TILE)
            self._edit_object_at(o.tile_x, o.tile_y)

    def _fill_list(self, category):
        default_kind, items = CATALOG[category]
        self.list.clear()
        for item in items:
            disp, mid, fp = item[0], item[1], item[2]
            kind = item[3] if len(item) > 3 else default_kind
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
        self.weapon_row.setVisible(mid in WEAPON_UNITS)

    # --- Karte ---
    def choose_map(self):
        dlg = MapDialog(self, self.res.names(), self.map_name, self.mission_name)
        if dlg.exec() == QDialog.Accepted:
            self.mission_name = dlg.name_edit.text().strip() or "Editor Mission"
            self.load_map(dlg.combo.currentText())
            self.setWindowTitle(f"OP2 Mission Editor — {self.mission_name}")

    def edit_players(self):
        dlg = PlayersDialog(self, self.players)
        if dlg.exec() == QDialog.Accepted:
            self.players = dlg.players
            self._refresh_player_range()
            self._refresh_overview()
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
            self._refresh_overview()
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
            self._refresh_overview()
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
            self._refresh_overview()
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
            "assignToGroup": "Gebaeude-Position mit Linksklick setzen",
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
        if self._action_pick and self._action_pick["kind"] in ("recordBuilding", "assignToGroup"):
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
            appconfig.set_output(self.output_dir, self.dll_name)
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
                "defeats": [asdict(c) for c in self.defeats],
                "node_positions": self.node_positions}
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
        # Knotenpositionen in-place aktualisieren (Timeline haelt eine Referenz darauf)
        self.node_positions.clear()
        self.node_positions.update(data.get("node_positions", {}))
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
                    actions = [action_from_dict(a) for a in td.pop("actions", [])]
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
        self._refresh_overview()
        self.statusBar().showMessage(
            f"Geladen: {path} ({len(self.objects)} Objekte, "
            f"{len(self.groups) + len(self.building_groups) + len(self.reinforce_groups)} Gruppe(n))")

    def load_map(self, name):
        try:
            self.map = Op2Map(self.res.read_file(name))
            arr = np.ascontiguousarray(render_array(self.map, self.res))
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
        self._refresh_overview()

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
        if self._action_pick and self._action_pick["kind"] == "assignToGroup":
            if self.map is None or not (0 <= tx < self.map.width and 0 <= ty < self.map.height):
                return
            action = TriggerAction(
                kind="assignToGroup",
                group_name=self._action_pick["group_name"],
                building_type=self._action_pick["building_type"],
                player=self._action_pick.get("player", 0),
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
        if mid in WEAPON_UNITS:
            params["weapon"] = self.weapon_combo.currentData()
        player = self.player_spin.value() if kind in ("structure", "vehicle") else 0
        unit_name = self.unit_name_edit.text().strip() if kind in ("structure", "vehicle") else ""
        obj = PlacedObject(kind, tx, ty, mid, fp, disp, player, params, self._new_object_uid(), unit_name)
        self._draw(obj)
        self.objects.append(obj)
        self._refresh_overview()
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
            self._refresh_overview()
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
        self._refresh_overview()
        self.statusBar().showMessage("Objekte geleert.")

    # --- Build ---
    def build_mission(self) -> Mission:
        # Offset +31/-1 wird im Codegen ergaenzt (MkXY fuer Einheiten, XYPos fuer Beacons/Walls).
        units, beacons, walls = [], [], []
        for o in self.objects:
            if o.kind in ("structure", "vehicle"):
                units.append(UnitSpec(
                    o.map_id, x=o.tile_x, y=o.tile_y, player=o.player,
                    cargo=o.params.get("weapon", "mapNone"),
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


