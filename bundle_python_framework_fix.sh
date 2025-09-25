#!/usr/bin/env bash
# bundle_python_framework_fix.sh (v2, Bash 3.2 compatible)
set -euo pipefail

APP="${1:-}"
if [[ -z "$APP" || ! -d "$APP/Contents" ]]; then
  echo "Usage: $0 \"/path/to/Data Assessment Tool.app\"" >&2
  exit 2
fi

BIN_DIR="$APP/Contents/Resources/venv/bin"
BIN=""
for c in "python3.12" "python3" "python"; do
  if [[ -x "$BIN_DIR/$c" ]]; then BIN="$BIN_DIR/$c"; break; fi
done
if [[ -z "$BIN" ]]; then
  echo "ERROR: No executable python found under $BIN_DIR" >&2
  exit 3
fi

echo "== Using interpreter: $BIN =="
echo "== Before =="
otool -L "$BIN" || true

# If already using bundled framework, nothing to do
if otool -L "$BIN" | grep -q "@executable_path/../Resources/Python.framework/Versions/"; then
  echo "Interpreter already linked to bundled Python.framework. Skipping interpreter patch."
  FWK_SYS_DETECT=""
else
  # Extract a /Library/Frameworks reference if present
  FWK_SYS_DETECT="$(otool -L "$BIN" | sed -n 's#^[[:space:]]*\(/Library/Frameworks/Python\.framework/Versions/[^/]*/Python\).*#\1#p' | head -n1)"
fi

if [[ -n "${FWK_SYS_DETECT:-}" ]]; then
  FWK_VER="$(echo "$FWK_SYS_DETECT" | sed -n 's#.*Versions/\([^/]*\)/Python#\1#p')"
  NEW_REF="@executable_path/../Resources/Python.framework/Versions/$FWK_VER/Python"
  FWK_LOCAL="$APP/Contents/Resources/Python.framework/Versions/$FWK_VER/Python"
  if [[ ! -f "$FWK_LOCAL" ]]; then
    echo "ERROR: Bundled framework not found at: $FWK_LOCAL" >&2
    exit 5
  fi
  echo "== Patching interpreter reference =="
  install_name_tool -change "$FWK_SYS_DETECT" "$NEW_REF" "$BIN"
else
  echo "No /Library/Frameworks reference detected in interpreter (or already patched)."
fi

# Patch any .so/.dylib still referencing /Library/Frameworks/Python.framework
echo "== Scanning for modules referencing system Python.framework =="
FWK_REGEX='/Library/Frameworks/Python.framework/Versions/'
find "$APP" -type f \( -name "*.so" -o -name "*.dylib" \) -print0 2>/dev/null | \
while IFS= read -r -d '' f; do
  if otool -L "$f" 2>/dev/null | grep -q "$FWK_REGEX"; then
    echo "  Patching: $f"
    # Extract the exact path to replace
    OLD="$(otool -L "$f" | sed -n 's#^[[:space:]]*\(/Library/Frameworks/Python\.framework/Versions/[^/]*/Python\).*#\1#p' | head -n1)"
    if [[ -n "$OLD" ]]; then
      # Use the interpreter's resolved NEW_REF if we computed it; else derive version from OLD
      if [[ -z "${NEW_REF:-}" ]]; then
        VER="$(echo "$OLD" | sed -n 's#.*Versions/\([^/]*\)/Python#\1#p')"
        NEW_REF="@executable_path/../Resources/Python.framework/Versions/$VER/Python"
      fi
      install_name_tool -change "$OLD" "$NEW_REF" "$f" || true
    fi
  fi
done

echo "== After =="
otool -L "$BIN" || true

echo "== Ad-hoc signing (deep) =="
codesign -s - --force --deep "$APP" || true

echo "Done. Re-zip and test in the VM."
