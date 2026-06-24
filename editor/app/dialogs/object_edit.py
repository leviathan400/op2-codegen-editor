from __future__ import annotations
from ..common import *
from ..placed_object import PlacedObject


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


