#!/usr/bin/env bash
# ==========================================================
#  DJ Paradise  -  HB Software  -  https://hbcs.info
#  Linux: run ./start-dj-paradise.sh  Installs anything missing.
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
  for c in python3.13 python3.12 python3.11 python3.10 python3.14 python3; do
    if command -v "$c" >/dev/null 2>&1 && "$c" "$LAUNCHER" --check >/dev/null 2>&1; then
      PY="$(command -v "$c")"
      return 0
    fi
  done
  return 1
}

if ! find_python; then
  echo "  Installing Python and window support (you may be asked for your password)..."
  if command -v apt-get >/dev/null 2>&1; then
    sudo apt-get update -y && sudo apt-get install -y python3 python3-venv python3-tk python3-pip
  elif command -v dnf >/dev/null 2>&1; then
    sudo dnf install -y python3 python3-tkinter python3-pip
  elif command -v pacman >/dev/null 2>&1; then
    sudo pacman -Sy --noconfirm python tk
  elif command -v zypper >/dev/null 2>&1; then
    sudo zypper install -y python3 python3-tk python3-pip
  fi
  find_python
fi

if [ -z "$PY" ]; then
  echo ""
  echo "  DJ Paradise needs Python 3.10 - 3.14 with Tk support."
  echo "  Install it with your package manager and run this again."
  exit 1
fi

nohup "$PY" "$LAUNCHER" >/dev/null 2>&1 &
exit 0
