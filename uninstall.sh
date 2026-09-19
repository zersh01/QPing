#!/usr/bin/env bash
# QPing uninstaller
APP_ID="qping"

rm -f "$HOME/.local/share/applications/$APP_ID.desktop"

for d in "$HOME/Desktop" "$HOME/Рабочий стол" "$HOME/Рабочий_стол"; do
    [ -d "$d" ] && rm -f "$d/$APP_ID.desktop"
done

update-desktop-database "$HOME/.local/share/applications" 2>/dev/null || true

echo "QPing удалён из меню и с рабочего стола."
echo "Настройки и история в ~/.config/QPing сохранены."
