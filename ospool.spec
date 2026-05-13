# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for ospool-manager.
# Build with:  pyinstaller ospool.spec
#
# The htcondor wheel bundles its own C++ shared libraries inside the wheel,
# so --collect-all htcondor picks up everything — no system HTCondor install needed.

from PyInstaller.utils.hooks import collect_all

htcondor_datas, htcondor_binaries, htcondor_hiddenimports = collect_all("htcondor")
classad_datas, classad_binaries, classad_hiddenimports = collect_all("classad")

a = Analysis(
    ["build_entry.py"],
    pathex=[],
    binaries=htcondor_binaries + classad_binaries,
    datas=htcondor_datas + classad_datas,
    hiddenimports=(
        htcondor_hiddenimports
        + classad_hiddenimports
        + [
            "ospool.cli",
            "ospool.config",
            "ospool.remote",
            "ospool.submit",
            "ospool.monitor",
            "ospool.fetch",
            "ospool.upload",
            "ospool.osdf",
            "ospool.token",
            "ospool.runs",
            "ospool.stage",
            "ospool.watcher",
            "typer",
            "rich",
            "tomli",
            "tomllib",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ospool",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,        # UPX can break .so files inside the bundle
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
