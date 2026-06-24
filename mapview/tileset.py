"""Decoder fuer OP2 Custom-Tilesets (well####.bmp im "PBMP"-Format).

Nachgebaut aus OP2Utility/src/Sprite/TilesetLoader.cpp + TilesetHeaders.h.
Aufbau:
  SectionHeader "PBMP" (8B)
  TilesetHeader: "head"(8B) + tagCount,pixelWidth,pixelHeight,bitDepth,flags (5*u32=20B)
  PpalHeader:    "PPAL"(8B) + "head"(8B) + tagCount(u32=4B)
  paletteHeader: "data"(8B) + 256*4B Palette  (R/B getauscht ggue. Standard-BMP)
  pixelHeader:   "data"(8B) + width*height B   (8bpp Indizes, top-down)
Tiles sind 32x32 und vertikal gestapelt (Tile t = Zeilen t*32 .. t*32+31).
"""
from __future__ import annotations

import struct
from dataclasses import dataclass

import numpy as np

TILE = 32


@dataclass
class Tileset:
    num_tiles: int
    palette: np.ndarray   # (256, 3) uint8, RGB
    pixels: np.ndarray    # (height, 32) uint8 Palettenindizes


def decode_tileset(data: bytes) -> Tileset:
    pos = 0

    def section() -> tuple[bytes, int]:
        nonlocal pos
        tag = data[pos:pos + 4]
        length = struct.unpack_from("<I", data, pos + 4)[0]
        pos += 8
        return tag, length

    tag, _ = section()
    assert tag == b"PBMP", f"kein PBMP: {tag!r}"

    tag, head_len = section()
    assert tag == b"head"
    tag_count, pw, ph, bit_depth, flags = struct.unpack_from("<5I", data, pos)
    pos += head_len
    assert pw == TILE and bit_depth == 8, f"unerwartet: w={pw} bpp={bit_depth}"

    # PPAL-Container
    tag, _ = section()
    assert tag == b"PPAL"
    tag, _ = section()
    assert tag == b"head"
    pos += 4  # tagCount im PPAL/head

    # Palette
    tag, pal_len = section()
    assert tag == b"data"
    pal_raw = np.frombuffer(data, dtype=np.uint8, count=pal_len, offset=pos).reshape(-1, 4)
    pos += pal_len
    # Datei speichert R,G,B,A; wir nehmen die ersten 3 Kanaele als RGB.
    palette = pal_raw[:, :3].copy()

    # Pixel
    tag, px_len = section()
    assert tag == b"data"
    pixels = np.frombuffer(data, dtype=np.uint8, count=px_len, offset=pos).reshape(ph, pw)

    return Tileset(num_tiles=ph // TILE, palette=palette, pixels=pixels)


def get_tile_rgb(ts: Tileset, graphic_index: int) -> np.ndarray:
    """32x32x3 RGB-Bild fuer einen Tile-Index."""
    block = ts.pixels[graphic_index * TILE:(graphic_index + 1) * TILE, :]  # (32,32)
    return ts.palette[block]  # (32,32,3)


if __name__ == "__main__":
    import sys
    from vol import VolFile
    vol = VolFile(sys.argv[1])
    ts = decode_tileset(vol.read_file(sys.argv[2]))
    print(f"{sys.argv[2]}: {ts.num_tiles} Tiles, Palette {ts.palette.shape}, Pixel {ts.pixels.shape}")
