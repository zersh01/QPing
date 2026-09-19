# help.py
"""
Справка QPing.

Чистый модуль без зависимостей от Qt и других модулей проекта.
Принимает функцию локализации `_` как аргумент, чтобы использовать
текущий язык приложения.
"""


def build_help_html(_):
    """Возвращает HTML-текст справки. `_` — функция gettext."""
    return (
        _("<h2>QPing Monitor User Guide</h2>") +
        _("<p>Monitor hosts via ICMP ping or TCP port check.</p>") +

        _("<h3>Keyboard shortcuts</h3>"
          "<ul>"
          "<li><b>Ctrl+N</b> — focus input field</li>"
          "<li><b>Delete</b> — delete selected hosts</li>"
          "<li><b>F2</b> — rename selected host</li>"
          "<li><b>Esc</b> — clear search field if focused, otherwise minimize to tray</li>"
          "<li><b>Ctrl+W</b> — close window</li>"
          "<li><b>Ctrl+Q</b> — quit</li>"
          "</ul>") +

        _("<h3>Host management</h3>"
          "<ul>"
          "<li><b>Select</b>: click for single, Ctrl+click for multi, Shift+click for range.</li>"
          "<li><b>Ping now</b>: check host immediately.</li>"
          "<li><b>Disable monitoring</b>: stop checking the host; it remains in the list (gray). "
          "The state persists across restarts.</li>"
          "<li><b>Clear History</b>: remove all records from memory and disk.</li>"
          "<li><b>Load Full History</b>: load all archived records for viewing.</li>"
          "<li><b>Search</b>: filter the host list by substring. Combined with 'Show Failed Hosts'.</li>"
          "</ul>") +

        _("<h3>Batch fping</h3>"
          "<p>If <code>fping</code> is installed, ICMP hosts are checked in batches "
          "of the size configured in Settings → General. Every timer tick a batch of ICMP hosts "
          "and one TCP host are checked.</p>") +

        _("<h3>Alerts</h3>"
          "<p>Configure threshold, reminder interval and recovery notifications "
          "in Application → Settings → Alerts.</p>") +

        _("<h3>Storage</h3>"
          "<p>History: <code>~/.config/QPing/history/&lt;host&gt;/YYYY-MM-DD.jsonl</code>.<br>"
          "Auto-cleanup in Application → Settings → Storage.</p>") +

        _("<h3>Hooks</h3>"
          "<p>External scripts triggered on host down/up transitions. "
          "See Settings → Hooks.</p>") +

        _("<h3>Ansible inventory import</h3>"
          "<p>Import → select <code>.ini</code> or <code>.yml</code>/<code>.yaml</code>. "
          "Groups become categories; ansible_host overrides hostname.</p>")
    )
