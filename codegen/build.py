"""Orchestriert: Mission-Modell -> LevelMain.cpp -> msbuild -> Mission-DLL.

Schreibt den generierten C++-Code in das (bewiesene) LevelTemplate-Projekt
und ruft msbuild ueber die VS-Entwicklerumgebung auf.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from codegen import generate_levelmain
from demo_mission import build_demo

HERE = Path(__file__).resolve().parent
TEMPLATE = HERE.parent / "LevelTemplate"
LEVELMAIN = TEMPLATE / "LevelMain.cpp"
VCXPROJ = TEMPLATE / "OP2Script.vcxproj"
VSDEVCMD = Path(
    r"C:\Program Files\Microsoft Visual Studio\18\Community\Common7\Tools\VsDevCmd.bat"
)


def write_levelmain(cpp: str) -> None:
    # Original einmalig sichern, damit das Template wiederherstellbar bleibt.
    backup = TEMPLATE / "LevelMain.cpp.orig"
    if not backup.exists() and LEVELMAIN.exists():
        shutil.copy2(LEVELMAIN, backup)
    LEVELMAIN.write_text(cpp, encoding="utf-8")
    print(f"[ok] LevelMain.cpp geschrieben ({len(cpp)} Zeichen)")


def build() -> Path:
    cmd = (
        f'"{VSDEVCMD}" -arch=x86 >nul 2>&1 && '
        f'msbuild "{VCXPROJ}" /p:Configuration=Release /p:Platform=Win32 '
        f"/v:minimal /nologo"
    )
    print("[..] msbuild laeuft ...")
    # Outpost2Path aus der Umgebung entfernen, damit der Post-Build-Schritt des
    # Templates NICHT zusaetzlich ctest.dll in den OP2-Ordner kopiert.
    # (Die DLL wird stattdessen vom Editor an den gewuenschten Ort gelegt.)
    env = {k: v for k, v in os.environ.items() if k.lower() != "outpost2path"}
    # shell=True: cmd-String direkt an cmd.exe geben, damit die verschachtelten
    # Anfuehrungszeichen korrekt ankommen (Liste + cmd /c verstuemmelt sie).
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, env=env)
    if result.returncode != 0:
        print(result.stdout[-3000:])
        print(result.stderr[-3000:])
        raise SystemExit(f"[FEHLER] Build fehlgeschlagen (Code {result.returncode})")

    dll = next((TEMPLATE / "Release").glob("*.dll"), None)
    if not dll:
        raise SystemExit("[FEHLER] Keine DLL im Release-Ordner gefunden")
    print(f"[ok] DLL: {dll}  ({dll.stat().st_size} Bytes)")
    return dll


def main() -> None:
    mission = build_demo()
    cpp = generate_levelmain(mission)
    write_levelmain(cpp)
    build()


if __name__ == "__main__":
    main()
