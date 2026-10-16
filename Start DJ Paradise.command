#!/bin/bash
# ==========================================================
#  DJ Paradise  -  HB Software  -  https://hbcs.info
#  macOS: double-click to start. Installs anything missing.
# ==========================================================
cd "$(dirname "$0")" || exit 1
LAUNCHER="$(pwd)/launcher.py"

echo ""
echo "  DJ PARADISE"
echo "  by HB Software"
echo ""
echo "  Checking your system..."

find_python() {
  PY=""
  for c in python3.13 python3.12 python3.11 python3.10 python3.14 python3 \
           /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 \
           /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
    if command -v "$c" >/dev/null 2>&1 && "$c" "$LAUNCHER" --check >/dev/null 2>&1; then
      PY="$(command -v "$c")"
      return 0
    fi
  done
  return 1
}

if ! find_python; then
  echo "  Installing Python (one-time setup, this can take a few minutes)..."
  if command -v brew >/dev/null 2>&1; then
    brew install python@3.12 python-tk@3.12
  else
    PKG="/tmp/djp-python-3.12.10.pkg"
    curl -fsSL -o "$PKG" "https://www.python.org/ftp/python/3.12.10/python-3.12.10-macos11.pkg" && \
      osascript -e "do shell script \"installer -pkg '$PKG' -target /\" with prompt \"DJ Paradise needs to install Python.\" with administrator privileges"
    rm -f "$PKG"
  fi
  find_python
fi

if [ -z "$PY" ]; then
  echo ""
  echo "  DJ Paradise could not set up Python automatically."
  echo "  Install Python 3.12 from https://www.python.org/downloads/ and start again."
  read -r -p "  Press Enter to close." _
  exit 1
fi

nohup "$PY" "$LAUNCHER" >/dev/null 2>&1 &
sleep 1
# Close this Terminal window when it was opened by a double-click.
osascript -e 'tell application "Terminal" to close (every window whose name contains "Start DJ Paradise")' >/dev/null 2>&1 &
exit 0
