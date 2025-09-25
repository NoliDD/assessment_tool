#!/usr/bin/env bash
# install_data_assessment_tool.sh
# Installs "Data Assessment Tool.app" from a .zip or .app, clears quarantine,
# optionally ad-hoc signs, and validates embedded Python with correct env.

set -eE -o pipefail

APP_DISPLAY_NAME="${APP_DISPLAY_NAME:-Data Assessment Tool}"
APP_BUNDLE_NAME="${APP_BUNDLE_NAME:-Data Assessment Tool.app}"
DEFAULT_INSTALL_DIR="/Applications"

ZIP_PATH=""
APP_SRC=""
INSTALL_DIR="$DEFAULT_INSTALL_DIR"
OPEN_AFTER=0
ADHOC_SIGN=0
DO_VALIDATE=0
MODULES="numpy,aiohttp,faiss,streamlit,httpx"

usage() {
  cat <<USAGE
Usage:
  $0 [--zip <path-to-zip>] [--app <path-to-app>] [--install-dir <dir>]
     [--open] [--adhoc] [--validate] [--modules <csv>]

Options:
  --zip PATH         Install from a .zip (preferred)
  --app PATH         Install from an existing .app bundle
  --install-dir DIR  Install location (default: $DEFAULT_INSTALL_DIR)
  --open             Open the app after install
  --adhoc            Ad-hoc codesign the app (no Developer ID required)
  --validate         Run embedded-Python import test after install
  --modules CSV      Modules to test during validation (default: $MODULES)

Examples:
  $0 --zip ~/Downloads/"$APP_DISPLAY_NAME"-1.0.0-arm64-mac.zip --open --validate
  $0 --app dist/mac-arm64/"$APP_BUNDLE_NAME" --adhoc --validate
USAGE
}

# --- parse args ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --zip) ZIP_PATH="$2"; shift 2;;
    --app) APP_SRC="$2"; shift 2;;
    --install-dir) INSTALL_DIR="$2"; shift 2;;
    --open) OPEN_AFTER=1; shift;;
    --adhoc) ADHOC_SIGN=1; shift;;
    --validate) DO_VALIDATE=1; shift;;
    --modules) MODULES="$2"; shift 2;;
    -h|--help) usage; exit 0;;
    *) echo "Unknown arg: $1"; usage; exit 2;;
  esac
done

# --- log file in Downloads ---
TS="$(date +%Y%m%d_%H%M%S)"
LOG="$HOME/Downloads/DataAssessmentTool_install_${TS}.log"
mkdir -p "$HOME/Downloads"
exec > >(tee -a "$LOG") 2>&1

echo "==> Log: $LOG"
echo "==> $(date)"
echo "==> Installing ${APP_DISPLAY_NAME}"

# --- helpers ---
die() { echo "ERROR: $*" >&2; exit 2; }
exists() { command -v "$1" >/dev/null 2>&1; }

# --- source discovery (zip or app) ---
if [[ -z "$ZIP_PATH" && -z "$APP_SRC" ]]; then
  # Try to auto-find a likely ZIP in Downloads
  CAND="$(ls "$HOME"/Downloads/*"$APP_DISPLAY_NAME"*mac*.zip 2>/dev/null | head -n1 || true)"
  if [[ -n "$CAND" ]]; then
    echo "==> Auto-detected ZIP: $CAND"
    ZIP_PATH="$CAND"
  else
    die "No --zip or --app provided, and no matching ZIP found in ~/Downloads"
  fi
fi

if [[ -n "$ZIP_PATH" && ! -f "$ZIP_PATH" ]]; then
  die "ZIP not found: $ZIP_PATH"
fi
if [[ -n "$APP_SRC" && ! -d "$APP_SRC" ]]; then
  die "App bundle not found: $APP_SRC"
fi

# --- install destination (fallback to ~/Applications if /Applications not writable) ---
DEST_DIR="$INSTALL_DIR"
if [[ ! -w "$INSTALL_DIR" ]]; then
  echo "WARN: $INSTALL_DIR not writable, falling back to ~/Applications"
  DEST_DIR="$HOME/Applications"
  mkdir -p "$DEST_DIR"
fi
DEST_APP="$DEST_DIR/$APP_BUNDLE_NAME"

# --- remove any existing app ---
if [[ -d "$DEST_APP" ]]; then
  echo "==> Removing existing: $DEST_APP"
  rm -rf "$DEST_APP"
fi

# --- extract or copy ---
if [[ -n "$ZIP_PATH" ]]; then
  echo "==> Unpacking ZIP: $ZIP_PATH"
  [[ -f "$ZIP_PATH" ]] || die "ZIP not found: $ZIP_PATH"
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  # Use ditto to preserve attributes
  /usr/bin/ditto -x -k "$ZIP_PATH" "$STAGE"
  # Find .app inside
  APP_SRC_FOUND="$(find "$STAGE" -maxdepth 3 -type d -name "*.app" -print | head -n1 || true)"
  [[ -n "$APP_SRC_FOUND" ]] || die "No .app found inside ZIP"
  echo "==> Installing to: $DEST_APP"
  /usr/bin/ditto "$APP_SRC_FOUND" "$DEST_APP"
else
  echo "==> Installing from .app: $APP_SRC -> $DEST_APP"
  /usr/bin/ditto "$APP_SRC" "$DEST_APP"
fi

# --- clear quarantine ---
echo "==> Clearing quarantine attribute"
if exists xattr; then
  /usr/bin/xattr -dr com.apple.quarantine "$DEST_APP" || true
fi

# --- optional ad-hoc sign ---
if [[ "$ADHOC_SIGN" -eq 1 ]]; then
  echo "==> Ad-hoc signing (deep, no timestamp)"
  if exists codesign; then
    /usr/bin/codesign --force --deep -s - --timestamp=none "$DEST_APP" || echo "WARN: codesign had warnings/errors (continuing)"
  else
    echo "WARN: codesign not available; skipping ad-hoc signing"
  fi
fi

# --- optional validation using embedded Python ---
if [[ "$DO_VALIDATE" -eq 1 ]]; then
  echo "==> Validating embedded Python & imports"
  RES="$DEST_APP/Contents/Resources"
  PY_HOME="$RES/python"
  VENV="$RES/venv"

  # pick interpreter: prefer venv, else runtime
  if [[ -x "$VENV/bin/python3" ]]; then
    PY="$VENV/bin/python3"
  elif [[ -x "$VENV/bin/python" ]]; then
    PY="$VENV/bin/python"
  elif [[ -x "$PY_HOME/bin/python3" ]]; then
    PY="$PY_HOME/bin/python3"
  else
    die "No embedded Python found under $RES (looked in venv/bin and python/bin)"
  fi

  # stdlib dir (python3.12 or python3.10, etc.)
  if [[ -d "$PY_HOME/lib/python3.12" ]]; then
    STD="python3.12"
  else
    STD="$(basename "$(ls -d "$PY_HOME"/lib/python3.* 2>/dev/null | head -n1)")"
  fi
  [[ -n "$STD" ]] || die "Could not determine stdlib dir under $PY_HOME/lib"

  # env like the app does
  export PYTHONHOME="$PY_HOME"
  export PYTHONPATH="$PY_HOME/lib/$STD:$PY_HOME/lib/$STD/lib-dynload:$RES:$RES/agents:$RES/pages:$RES/reporting:$RES/utils"
  if [[ "$PY" == "$VENV/bin/"* ]]; then
    export DYLD_LIBRARY_PATH="$VENV/lib"
  fi
  echo "   PYTHONHOME = $PYTHONHOME"
  echo "   PYTHONPATH = $PYTHONPATH"
  [[ -n "${DYLD_LIBRARY_PATH:-}" ]] && echo "   DYLD_LIBRARY_PATH = $DYLD_LIBRARY_PATH"

  # import test
  MODULES_ENV="$MODULES" "$PY" - <<'PY'
import os, sys, platform, importlib
mods=[m.strip() for m in os.getenv("MODULES_ENV","").split(",") if m.strip()]
print("Python:", sys.version.split()[0], "| Platform:", platform.platform())
print("Testing imports:", mods)
failed=[]
for m in mods:
    try:
        importlib.import_module(m); print("OK", m)
    except Exception as e:
        print("FAIL", m, "->", e); failed.append(m)
print("RESULT", "PASS" if not failed else "FAIL", failed)
sys.exit(0 if not failed else 3)
PY
  VALID_RC=$? || true
  if [[ $VALID_RC -ne 0 ]]; then
    echo "WARN: Import test failed (rc=$VALID_RC). See log for details: $LOG"
  else
    echo "==> Validation PASS"
  fi
fi

# --- open after install ---
if [[ "$OPEN_AFTER" -eq 1 ]]; then
  echo "==> Opening app"
  /usr/bin/open "$DEST_APP" || echo "WARN: open failed"
fi

echo "==> Done. Log saved to: $LOG"