#!/usr/bin/env bash
# QPing launcher — robust startup with automatic discovery of a python
# interpreter that has PyQt6 installed.
# Logging is handled by qp_logging.setup_logging() in Python:
#   ~/.config/QPing/qping.log (rotated at 1 MB, 3 backups).
# Required for the .desktop shortcuts.

cd "$(dirname "$(readlink -f "$0")")" || exit 1

mkdir -p "$HOME/.config/QPing"

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
    echo "ERROR: python3 with PyQt6 not found." >&2
    echo "  Checked: ~/myenv, ./venv, ./.venv, ~/.local/bin, /usr/bin" >&2
    echo "  Install PyQt6: pip install PyQt6" >&2
    exit 1
fi

exec "$PY" qping "$@"
