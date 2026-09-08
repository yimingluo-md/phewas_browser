# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the phewas-server sidecar (one directory, started by the desktop shell).

Build with scripts/build_sidecar.sh; do not run pyinstaller by hand unless debugging.
"""
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

block_cipher = None

datas, binaries, hiddenimports = [], [], []
for pkg in ("duckdb", "uvicorn", "fastapi", "starlette", "pydantic", "pydantic_core", "anyio"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("phewas_core")            # builtin profiles + phecode dictionary
hiddenimports += collect_submodules("phewas_core") + collect_submodules("phewas_server")
hiddenimports += ["uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
                  "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on"]

a = Analysis(
    ["entry.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "test", "unittest", "pydoc", "doctest", "numpy", "pandas", "pyarrow", "IPython"],
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="phewas-server",
    debug=False,
    strip=False,
    upx=False,
    console=True,           # keeps stdout for the PHEWAS_URL handshake; the shell hides the window on Windows
    disable_windowed_traceback=False,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, strip=False, upx=False, name="phewas-server")
