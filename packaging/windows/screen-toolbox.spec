# -*- mode: python -*-
# PyInstaller (modo pasta) para o Windows, a partir do Python/GTK/GStreamer do MSYS2 UCRT64.
# Uso: packaging/windows/build.sh (gera os .ico em build/windows/icons antes).

import os
import shutil
from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

ROOT = Path(SPECPATH).resolve().parents[1]
ICONS = ROOT / "build" / "windows" / "icons"
APP_ID = "io.github.nicolas.ScreenToolbox"

# o GLib sobe o D-Bus de sessão (instância única do app) com o gdbus.exe que estiver
# na mesma pasta da libgio
gdbus = shutil.which("gdbus.exe") or shutil.which("gdbus")

datas = [(str(p), "data") for p in (ROOT / "data").glob("*.svg")]
datas += [(str(p), "data") for p in ICONS.glob("*.ico")]

a = Analysis(
    [str(ROOT / "packaging" / "windows" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[(gdbus, ".")] if gdbus else [],
    datas=datas,
    hiddenimports=collect_submodules("screen_toolbox"),
    hooksconfig={
        "gi": {
            "icons": ["Adwaita", "hicolor"],
            "themes": ["Adwaita"],
            "languages": ["pt_BR"],
            "module-versions": {"Gtk": "4.0", "Gdk": "4.0", "Adw": "1", "Gst": "1.0"},
        },
        "gstreamer": {
            # só os plugins usados pelo app (o GStreamer completo passa de 300 MB)
            "include_plugins": [
                "coreelements", "app", "typefindfunctions", "videotestsrc",
                "videoconvertscale", "videoconvert", "videoscale", "videocrop", "videorate",
                "videofilter", "cairo", "audioconvert", "audioresample", "audiomixer",
                "audiorate", "audiotestsrc", "volume",
                "d3d11", "wasapi2", "wasapi", "mediafoundation",
                "x264", "openh264", "libav", "isomp4", "videoparsersbad", "audioparsers",
                "matroska", "vpx", "opus", "vorbis", "ogg",
            ],
        },
    },
    excludes=["tkinter", "unittest", "pydoc", "test"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="screen-toolbox",
    icon=str(ICONS / f"{APP_ID}.ico"),
    console=False,
    version=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="screen-toolbox",
)
