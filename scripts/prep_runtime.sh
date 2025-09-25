#!/usr/bin/env bash
# scripts/prep_runtime.sh
# Prepare a self-contained Python runtime for bundling with Electron.
# - Unpack CPython "install_only" tarball to ./python
# - If libpython exists -> create venv + copy dylib into venv/lib (dyld fix)
# - Else -> install deps into runtime prefix (no venv)
# - Install requirements, run sanity imports, prune caches
# macOS Bash 3.2 compatible.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"; cd "$ROOT"

RUNTIME_TGZ="${RUNTIME_TGZ:-runtime/python.tar.gz}"
PYDIR="python"       # becomes Contents/Resources/python
VENV="venv"          # becomes Contents/Resources/venv
MODULES="${MODULES:-numpy,aiohttp,faiss,streamlit,httpx}"

bold(){ printf "\033[1m%s\033[0m\n" "$*"; }
info(){ echo "==> $*"; }
warn(){ echo "WARN: $*" >&2; }
fail(){ echo "ERROR: $*" >&2; exit 2; }

# If default archive missing, auto-pick first runtime/*.tar*
if [[ ! -f "$RUNTIME_TGZ" && -d runtime ]]; then
  CAND="$(ls runtime/*.tar* 2>/dev/null | head -n1 || true)"
  if [[ -n "$CAND" ]]; then
    warn "RUNTIME_TGZ not found; auto-using: $CAND"
    RUNTIME_TGZ="$CAND"
  fi
fi
[[ -f "$RUNTIME_TGZ" ]] || fail "Missing $RUNTIME_TGZ — use an *install_only* aarch64-apple-darwin CPython archive."

rm -rf "$PYDIR" "$VENV"

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

bold "Unpacking runtime: $RUNTIME_TGZ"
case "$RUNTIME_TGZ" in
  *.tar.gz|*.tgz) tar -xzf "$RUNTIME_TGZ" -C "$TMP" ;;
  *.tar.zst)
    if command -v unzstd >/dev/null 2>&1; then unzstd -c "$RUNTIME_TGZ" | tar -x -C "$TMP"
    elif command -v zstd   >/dev/null 2>&1; then zstd  -dc "$RUNTIME_TGZ" | tar -x -C "$TMP"
    else fail "Archive is .tar.zst. Install zstd (e.g., brew install zstd)."; fi
    ;;
  *.tar) tar -xf "$RUNTIME_TGZ" -C "$TMP" ;;
  *) fail "Unsupported archive format: $RUNTIME_TGZ" ;;
esac

# Find a python3(.X) under */bin/*
PYFOUND="$(
  find "$TMP" -type f -path '*/bin/*' -print 2>/dev/null | grep -E '/bin/python3(\.[0-9]+)?$' | head -n1 || true
)"
if [[ -z "$PYFOUND" ]]; then
  warn "Extracted tree (top):"; (cd "$TMP" && find . -maxdepth 3 -print | sed -n '1,80p') || true
  fail "No python3(.X) under */bin/* — ensure this is an *install_only* runtime (not sources/debug)."
fi

PREFIX_DIR="$(cd "$(dirname "$PYFOUND")/.." && pwd)"
info "Detected Python prefix: $PREFIX_DIR"

# Copy prefix -> ./python (dereference symlinks)
rm -rf "$PYDIR"; mkdir -p "$PYDIR"
if command -v rsync >/dev/null 2>&1; then rsync -aL "$PREFIX_DIR/" "$PYDIR/"; else ditto "$PREFIX_DIR" "$PYDIR"; fi

# Resolve interpreter
PY="$PYDIR/bin/python3"
if [[ ! -x "$PY" ]]; then PY="$(printf '%s\n' "$PYDIR"/bin/python3.* | head -n1)"; fi
[[ -x "$PY" ]] || fail "After extraction, no python3 under $PYDIR/bin"
"$PY" -V

# Helper: site-packages dir for a given python executable
site_dir_for_exec() {
  "$1" - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
}

# Helper: seed pip from offline wheelhouse into a given python executable
seed_pip_from_wheelhouse_exec() {
  local PYEXEC="$1"
  local WHEELHOUSE="runtime/wheelhouse"
  [[ -d "$WHEELHOUSE" ]] || fail "ensurepip unavailable and no wheelhouse.\nRun: python3 -m pip download pip setuptools wheel -d runtime/wheelhouse"

  local PIP_WHL SETUP_WHL WHEEL_WHL SITE
  PIP_WHL="$(ls -1 "$WHEELHOUSE"/pip-*.whl 2>/dev/null | sort | tail -n1 || true)"
  SETUP_WHL="$(ls -1 "$WHEELHOUSE"/setuptools-*.whl 2>/dev/null | sort | tail -n1 || true)"
  WHEEL_WHL="$(ls -1 "$WHEELHOUSE"/wheel-*.whl 2>/dev/null | sort | tail -n1 || true)"
  [[ -n "$PIP_WHL" && -n "$SETUP_WHL" && -n "$WHEEL_WHL" ]] || fail "wheelhouse missing pip/setuptools/wheel."

  SITE="$(site_dir_for_exec "$PYEXEC")"
  info "Bootstrapping pip into: $SITE"
  "$PYEXEC" - <<PY
import zipfile
site = r"""$SITE"""
for wh in [r"""$SETUP_WHL""", r"""$WHEEL_WHL""", r"""$PIP_WHL"""]:
    with zipfile.ZipFile(wh) as zf:
        zf.extractall(site)
print("Bootstrapped pip/setuptools/wheel into", site)
PY
  "$PYEXEC" -m pip --version || true
}

# Choose path: venv (if libpython exists) OR prefix install
LIBPY_CAND="$(ls -1 "$PYDIR"/lib/libpython3.*.dylib 2>/dev/null | head -n1 || true)"
if [[ -n "$LIBPY_CAND" ]]; then
  ########################################################################
  # VENV BRANCH (shared libpython present)
  ########################################################################
  bold "Shared libpython found → using venv"
  "$PY" -m venv --copies --without-pip "$VENV"

  VPY="$VENV/bin/python"
  mkdir -p "$VENV/lib"

  # Determine the filename venv expects; default to basename from runtime
  EXPECTED="$(basename "$LIBPY_CAND")"
  if command -v otool >/dev/null 2>&1; then
    GOT="$(otool -L "$VPY" | awk '/libpython3/{print $1; exit}')"
    BN="$(basename "$GOT" 2>/dev/null || true)"
    if [[ -n "${BN:-}" ]]; then EXPECTED="$BN"; fi
  fi

  # Copy (not symlink) so a real file exists at venv/lib/<expected>
  cp -a "$LIBPY_CAND" "$VENV/lib/$EXPECTED"
  echo "Placed $VENV/lib/$EXPECTED"

  # Wrapper to run venv python with DYLD_LIBRARY_PATH set
  run_vpy(){ DYLD_LIBRARY_PATH="$VENV/lib" "$VPY" "$@"; }

  bold "Seeding pip (ensurepip)…"
  set +e
  run_vpy -m ensurepip --upgrade --default-pip
  EP_RC=$?
  set -e
  if [[ $EP_RC -ne 0 ]]; then
    warn "ensurepip failed; using wheelhouse fallback"
    # Inline wheelhouse bootstrap for the venv
    SITE="$(run_vpy - <<'PY'
import sysconfig
print(sysconfig.get_paths()['purelib'])
PY
)"
    WHEELHOUSE="runtime/wheelhouse"
    PIP_W="$(ls -1 "$WHEELHOUSE"/pip-*.whl 2>/dev/null | sort | tail -n1 || true)"
    SET_W="$(ls -1 "$WHEELHOUSE"/setuptools-*.whl 2>/dev/null | sort | tail -n1 || true)"
    WHL_W="$(ls -1 "$WHEELHOUSE"/wheel-*.whl 2>/dev/null | sort | tail -n1 || true)"
    [[ -n "$PIP_W" && -n "$SET_W" && -n "$WHL_W" ]] || fail "wheelhouse missing pip/setuptools/wheel."
    DYLD_LIBRARY_PATH="$VENV/lib" "$VPY" - <<PY
import zipfile
site=r"""$SITE"""
for wh in [r"""$SET_W""", r"""$WHL_W""", r"""$PIP_W"""]:
    with zipfile.ZipFile(wh) as zf: zf.extractall(site)
print("Bootstrapped pip/setuptools/wheel into", site)
PY
  fi

  # Tooling + requirements
  run_vpy -m pip install --upgrade --no-input --no-color pip setuptools wheel
  if [[ -d runtime/wheelhouse && -f requirements.txt ]]; then
    info "Installing requirements (offline)"
    run_vpy -m pip install --no-input --no-color --no-index --find-links runtime/wheelhouse -r requirements.txt
  elif [[ -f requirements.txt ]]; then
    info "Installing requirements (online)"
    run_vpy -m pip install --no-input --no-color -r requirements.txt
  else
    warn "requirements.txt not found; skipping dependency install."
  fi

  # Sanity import test
  bold "Sanity import test (venv)"
  set +e
  MODULES_ENV="$MODULES" DYLD_LIBRARY_PATH="$VENV/lib" "$VPY" - <<'PY'
import os, importlib, sys, platform
mods=[m.strip() for m in os.getenv("MODULES_ENV","").split(",") if m.strip()]
print("Python:", sys.version.split()[0], "| Platform:", platform.platform())
print("Testing imports:", mods)
failed=[]
for m in mods:
    try: importlib.import_module(m); print("OK", m)
    except Exception as e: print("FAIL", m, "->", e); failed.append(m)
print("RESULT", "PASS" if not failed else "FAIL", failed)
PY
  TEST_RC=$?
  set -e

else
  ########################################################################
  # PREFIX BRANCH (no shared libpython → no venv)
  ########################################################################
  bold "No shared libpython in runtime → installing into the runtime prefix (no venv)"
  "$PY" -m ensurepip --upgrade --default-pip || true
  if ! "$PY" -m pip --version >/dev/null 2>&1; then
    seed_pip_from_wheelhouse_exec "$PY"
  fi

  "$PY" -m pip install --upgrade --no-input --no-color pip setuptools wheel
  if [[ -d runtime/wheelhouse && -f requirements.txt ]]; then
    info "Installing requirements into prefix (offline)"
    "$PY" -m pip install --no-input --no-color --no-index --find-links runtime/wheelhouse -r requirements.txt
  elif [[ -f requirements.txt ]]; then
    info "Installing requirements into prefix (online)"
    "$PY" -m pip install --no-input --no-color -r requirements.txt
  else
    warn "requirements.txt not found; skipping dependency install."
  fi

  bold "Sanity import test (prefix)"
  set +e
  MODULES_ENV="$MODULES" "$PY" - <<'PY'
import os, importlib, sys, platform
mods=[m.strip() for m in os.getenv("MODULES_ENV","").split(",") if m.strip()]
print("Python:", sys.version.split()[0], "| Platform:", platform.platform())
print("Testing imports:", mods)
failed=[]
for m in mods:
    try: importlib.import_module(m); print("OK", m)
    except Exception as e: print("FAIL", m, "->", e); failed.append(m)
print("RESULT", "PASS" if not failed else "FAIL", failed)
PY
  TEST_RC=$?
  set -e
fi

# Prune caches
bold "Pruning caches"
find "$PYDIR" ${VENV:+ "$VENV"} -name __pycache__ -type d -prune -exec rm -rf {} + || true
[[ -d "$VENV" ]] && find "$VENV" -type f -name "*.py[co]" -delete || true

echo
bold "Runtime ready"
echo "  - Python prefix: $PYDIR"
[[ -d "$VENV" ]] && echo "  - Venv         : $VENV (dyld fix applied)" || echo "  - Venv         : (not used)"
if [[ ${TEST_RC:-0} -eq 0 ]]; then echo "  - Import test  : PASS"; else echo "  - Import test  : FAIL (see above)"; fi