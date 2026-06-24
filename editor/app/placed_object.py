from __future__ import annotations
from .common import *


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


