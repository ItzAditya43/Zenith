# PyInstaller spec — freezes the FastAPI backend into a single self-contained
# executable so the desktop app can ship it as a Tauri sidecar and end users
# don't need Python installed.
#
#   pip install pyinstaller
#   pyinstaller cortex-backend.spec
#   -> dist/cortex-backend  (or dist/cortex-backend.exe on Windows)
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

binaries = (
    collect_dynamic_libs("ctranslate2")
    + collect_dynamic_libs("onnxruntime")
    + collect_dynamic_libs("av")
    + collect_dynamic_libs("sqlite_vec")
)

datas = (
    collect_data_files("faster_whisper")
    + collect_data_files("sqlite_vec")
)

a = Analysis(
    ["run_frozen.py"],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="cortex-backend",
    console=True,
    disable_windowed_traceback=False,
    strip=False,
    upx=False,
)
