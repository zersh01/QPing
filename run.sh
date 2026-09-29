#!/usr/bin/env bash
# QPing launcher — robust startup with automatic discovery of a python
# interpreter that has PyQt6 installed.
# Error log: ~/.config/QPing/qping.log
# Required for the .desktop shortcuts.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

LOG="$HOME/.config/QPing/qping.log"
mkdir -p "$(dirname "$LOG")"

# Find a python with PyQt6, in priority order:
#   1. the user's myenv (current installation)
#   2. venv/ or .venv/ next to the project
#   3. ~/.local/bin/python3 (user-level pip --user)
#   4. system python3
PY=""
for candidate in \
    "$HOME/myenv/bin/python3" \
    "./venv/bin/python3" \
    "./.venv/bin/python3" \
    "$HOME/.local/bin/python3" \
    "/usr/bin/python3"
do
    if [ -x "$candidate" ] && "$candidate" -c "import PyQt6" >/dev/null 2>&1; then
        PY="$candidate"
        break
    fi
done

if [ -z "$PY" ]; then
    echo "[$(date '+%F %T')] ERROR: python3 with PyQt6 not found." >> "$LOG"
    echo "  Checked: ~/myenv, ./venv, ./.venv, ~/.local/bin, /usr/bin" >> "$LOG"
    echo "  Install PyQt6: pip install PyQt6" >> "$LOG"
    exit 1
fi

echo "[$(date '+%F %T')] START $PY qping $*" >> "$LOG"
exec "$PY" qping "$@" 2>>"$LOG"
