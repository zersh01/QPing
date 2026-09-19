#!/usr/bin/env bash
# QPing installer v2.0
# Устанавливает .desktop-файл в меню приложений и на рабочий стол.
# Иконка берётся из рабочего каталога: $SCRIPT_DIR/qping.svg

set -e

APP_NAME="QPing"
APP_VERSION="2.0"
APP_ID="qping"

# --- Определяем рабочий каталог (где лежит этот скрипт) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$SCRIPT_DIR/run.sh"
ICON_PATH="$SCRIPT_DIR/qping.svg"

# --- Проверки ---
if [ ! -f "$RUNNER" ]; then
    echo "Ошибка: не найден $RUNNER"
    exit 1
fi

if [ ! -f "$ICON_PATH" ]; then
    echo "Ошибка: не найдена иконка $ICON_PATH"
    exit 1
fi

chmod +x "$RUNNER"

# --- Содержимое .desktop ---
DESKTOP_CONTENT="[Desktop Entry]
Type=Application
Version=$APP_VERSION
Name=$APP_NAME
Name[ru]=$APP_NAME
Comment=Network host monitor with ICMP ping and TCP port checks
Comment[ru]=Мониторинг хостов через ICMP ping и TCP-порты
Exec=$RUNNER
Icon=$ICON_PATH
Path=$SCRIPT_DIR
Terminal=false
Categories=Network;Monitor;Utility;
Keywords=ping;monitor;network;icmp;tcp;uptime;
StartupNotify=true
StartupWMClass=$APP_NAME"

# --- Установка в меню приложений ---
APPS_DIR="$HOME/.local/share/applications"
mkdir -p "$APPS_DIR"
printf '%s\n' "$DESKTOP_CONTENT" > "$APPS_DIR/$APP_ID.desktop"
chmod +x "$APPS_DIR/$APP_ID.desktop"

# --- Определяем папку рабочего стола ---
DESKTOP_DIR=""
for candidate in "$HOME/Desktop" "$HOME/Рабочий стол" "$HOME/Рабочий_стол"; do
    if [ -d "$candidate" ]; then
        DESKTOP_DIR="$candidate"
        break
    fi
done

if [ -z "$DESKTOP_DIR" ] && command -v xdg-user-dir >/dev/null 2>&1; then
    d=$(xdg-user-dir DESKTOP 2>/dev/null || true)
    if [ -n "$d" ] && [ -d "$d" ]; then
        DESKTOP_DIR="$d"
    fi
fi

if [ -z "$DESKTOP_DIR" ]; then
    DESKTOP_DIR="$HOME/Desktop"
    mkdir -p "$DESKTOP_DIR"
fi

printf '%s\n' "$DESKTOP_CONTENT" > "$DESKTOP_DIR/$APP_ID.desktop"
chmod +x "$DESKTOP_DIR/$APP_ID.desktop"

# GNOME требует явно помечать ярлыки как доверенные
gio set "$DESKTOP_DIR/$APP_ID.desktop" metadata::trusted true 2>/dev/null || true

# --- Обновление кэшей ---
update-desktop-database "$APPS_DIR" 2>/dev/null || true

# --- Итог ---
echo ""
echo "QPing $APP_VERSION установлен."
echo "  Меню приложений: $APPS_DIR/$APP_ID.desktop"
echo "  Рабочий стол:    $DESKTOP_DIR/$APP_ID.desktop"
echo "  Иконка:          $ICON_PATH"
echo "  Launcher:        $RUNNER"
echo "  Лог ошибок:      ~/.config/QPing/qping.log"
echo ""
echo "Для удаления запустите: ./uninstall.sh"
