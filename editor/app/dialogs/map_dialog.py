from __future__ import annotations
from ..common import *


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


