# OP2 Mission Editor

A Python-based mission editor for Outpost 2 that generates native C++ mission source code and compiles it to a 32-bit DLL.

## How it works

1. The **editor GUI** (PySide6) lets you place units, buildings, beacons, walls, configure players, triggers, and AI groups visually.
2. The **code generator** (`codegen/`) turns the mission model into a `.cpp` file.
3. **MSBuild / MSVC** compiles the `.cpp` into a 32-bit DLL that Outpost 2 loads directly.

## Repository layout

```
editor/         Python editor (PySide6)
  app/          Modular editor package (main entry point)
    dialogs/    All editor dialogs
  main.py       Legacy single-file editor (kept for reference)
codegen/        C++ code generator and mission data model
mapview/        Map tile renderer / inspection tools
missions/       Saved mission projects (.json)
LevelTemplate/  C++ mission template + bundled OP2 SDK sources
  OP2MissionSDK/
    Outpost2DLL/  Core SDK headers and lib
    OP2Helper/    Helper macros (MkXY, ExportLevelDetails, …)
    HFL/          Hooman's Function Library (UnitEx, PlayerEx, …)
    odasl/        odasl.lib
```

## Setup

### Requirements

- Python 3.11+
- PySide6 (`pip install PySide6`)
- Visual Studio Build Tools 2019+ with the **C++ x86/x64 Build Tools** component (for `msbuild`)
- Outpost 2 installed (OPU version recommended)

### Editor config

Copy `editor/config.example.json` to `editor/config.json` and adjust the paths:

```json
{
  "output_dir": "C:/Path/To/Outpost2/OPU",
  "dll_name": "cEditorMission.dll"
}
```

`config.json` is git-ignored (machine-specific paths).

### Start the editor

```powershell
cd editor
python -m app
```

### Build a mission DLL

Use the **Build** button in the editor, or run manually:

```powershell
cd LevelTemplate
msbuild OP2Script.vcxproj /p:Configuration=Release /p:Platform=Win32
```

The compiled DLL is written to the path set in `config.json`.

## SDK sources

`LevelTemplate/OP2MissionSDK/` contains the bundled SDK headers and libraries:

- [Outpost2DLL](https://github.com/OutpostUniverse/Outpost2DLL) — core game API
- [OP2Helper](https://github.com/OutpostUniverse/OP2Helper) — helper macros
- [HFL](https://github.com/OutpostUniverse/HFL) — extended unit/player API (UnitEx, PlayerEx, TethysGameEx)
- [odasl](https://github.com/OutpostUniverse/odasl) — audio lib

The SDK sources are bundled directly (no git submodules) so the project builds without any additional clones.
