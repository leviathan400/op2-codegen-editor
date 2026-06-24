from __future__ import annotations
from .common import *


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


