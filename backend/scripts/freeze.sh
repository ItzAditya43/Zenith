#!/usr/bin/env bash
# Freeze the backend into dist/zenith-backend[.exe] for the desktop sidecar.
# Used by CI and the release workflow so both build the same way.
#
# Windows runners taught us two things (see requirements-freeze.txt):
#  - PyInstaller resolves DLL dependencies through PATH, and hosted runners
#    put Java, ImageMagick and other toolchains on it: their DLLs were being
#    analysed (and could be bundled), and python-magic could load an
#    ImageMagick DLL as "libmagic" and crash or hang PyInstaller's import
#    subprocess. So PATH is reduced to Python + the OS.
#  - The import subprocess can still crash intermittently on native
#    libraries, so each attempt gets a timeout and we retry.
set -euo pipefail
cd "$(dirname "$0")/.."

PY_DIR="$(dirname "$(command -v python)")"
case "$(uname -s)" in
  MINGW*|MSYS*|CYGWIN*)
    export PATH="$PY_DIR:$PY_DIR/Scripts:/c/Windows/System32:/c/Windows:/usr/bin" ;;
  *)
    export PATH="$PY_DIR:/usr/local/bin:/usr/bin:/bin" ;;
esac
echo "freeze PATH=$PATH"

ATTEMPTS="${FREEZE_ATTEMPTS:-3}"
PER_ATTEMPT="${FREEZE_TIMEOUT_SECONDS:-900}"
for i in $(seq 1 "$ATTEMPTS"); do
  echo "::group::PyInstaller attempt $i/$ATTEMPTS"
  if python scripts/run_with_timeout.py "$PER_ATTEMPT" python -m PyInstaller zenith-backend.spec --noconfirm --workpath "build/attempt-$i"; then
    echo "::endgroup::"
    exit 0
  fi
  echo "::endgroup::"
  echo "attempt $i failed or timed out after ${PER_ATTEMPT}s"
done
echo "PyInstaller failed $ATTEMPTS times"
exit 1
