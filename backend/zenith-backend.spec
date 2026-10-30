# PyInstaller spec — freezes the FastAPI backend into a single self-contained
# executable so the desktop app can ship it as a Tauri sidecar and end users
# don't need Python installed.
#
#   pip install -r requirements-freeze.txt   (pinned toolchain)
#   pyinstaller zenith-backend.spec
#   -> dist/zenith-backend  (or dist/zenith-backend.exe on Windows)
#
# NOTE: several backend deps ship native libraries and/or load code lazily,
# which PyInstaller's static analysis can miss — they're listed explicitly in
# hiddenimports/collect_* below. faster-whisper (ctranslate2), onnxruntime,
# av, and sqlite-vec in particular need their data/binaries collected. Expect
# to iterate on this list per-platform the first time you build.
from PyInstaller.utils.hooks import collect_submodules, collect_dynamic_libs, collect_data_files

hiddenimports = (
    collect_submodules("uvicorn")
    + collect_submodules("app")
    + [
        "uvicorn.logging", "uvicorn.loops.auto", "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets.auto", "uvicorn.lifespan.on",
        "anyio._backends._asyncio",
    ]
)

import glob
import os
import sys

import sqlite_vec

# sqlite-vec's loadable extension must sit inside the bundled `sqlite_vec`
# package dir, where sqlite_vec.loadable_path() looks for it.
# collect_dynamic_libs() put it at the bundle root, so frozen builds silently
# lost vector search (rag.vec_unavailable: "vec0.so: cannot open shared
# object file").
_vec_dir = os.path.dirname(sqlite_vec.__file__)
_vec_libs = [(f, "sqlite_vec") for f in glob.glob(os.path.join(_vec_dir, "vec0.*"))
             if f.endswith((".so", ".dll", ".dylib"))]
if not _vec_libs:
    raise SystemExit(f"sqlite-vec loadable extension not found in {_vec_dir}")

binaries = (
    collect_dynamic_libs("ctranslate2")
    + collect_dynamic_libs("onnxruntime")
    + collect_dynamic_libs("av")
    + _vec_libs
)

datas = collect_data_files("faster_whisper")

a = Analysis(
    ["run_frozen.py"],
    pathex=["."],  # so `app` is importable during analysis
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # python-magic needs a native libmagic that Windows/macOS don't ship (and
    # on CI runners it found ImageMagick DLLs instead, crashing the build).
    # attachments.py already falls back to extension-based MIME detection.
    excludes=["tkinter", "matplotlib", "pytest"]
    + (["magic"] if sys.platform in ("win32", "darwin") else []),
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="zenith-backend",
    console=True,
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)
