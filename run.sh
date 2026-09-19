#!/usr/bin/env bash
# QPing launcher — устойчивый запуск с автоматическим поиском python с PyQt6.
# Лог ошибок: ~/.config/QPing/qping.log
# Требуется для ярлыков

cd "$(dirname "$(readlink -f "$0")")" || exit 1

LOG="$HOME/.config/QPing/qping.log"
mkdir -p "$(dirname "$LOG")"

# Ищем python с PyQt6 в порядке приоритета:
#   1. myenv пользователя (текущая установка)
#   2. venv/ или .venv/ рядом с проектом
#   3. ~/.local/bin/python3 (пользовательский pip --user)
#   4. системный python3
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
