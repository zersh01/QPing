# help.py
"""
QPing help text.

Pure module with no Qt or project dependencies.
Accepts the localization function `_` as an argument so that the current
UI language is used.
"""


def build_help_html(_):
    """Return the help HTML. `_` is the gettext function."""
    return (
        _("<h2>QPing Monitor User Guide</h2>")
        + _("<p>Monitor hosts via ICMP ping or TCP port check.</p>")

        + _("<h3>Keyboard shortcuts</h3>"
            "<ul>"
            "<li><b>Ctrl+F</b> — focus the search field</li>"
            "<li><b>Ctrl+N</b> — focus the host input field</li>"
            "<li><b>Ctrl+R</b> — cycle graph height (Compact → Normal → Expanded)</li>"
            "<li><b>Ctrl+W</b> — hide window to tray</li>"
            "<li><b>Ctrl+Q</b> — quit the application</li>"
            "<li><b>F2</b> — rename the selected host</li>"
            "<li><b>Delete</b> — delete the selected hosts</li>"
            "<li><b>Esc</b> — clear the search field if focused, otherwise hide to tray</li>"
            "</ul>")

        + _("<h3>Host management</h3>"
            "<ul>"
            "<li><b>Select</b>: click for a single host, Ctrl+click for multiple, Shift+click for a range.</li>"
            "<li><b>Ping now</b>: check the host immediately.</li>"
            "<li><b>Disable monitoring</b>: stop checking the host; it stays in the list (gray). "
            "The state persists across restarts.</li>"
            "<li><b>Mute notifications</b>: the host keeps being checked and its status/graph are updated, "
            "but tray notifications are suppressed. The state persists across restarts.</li>"
            "<li><b>Clear History</b>: remove all records from memory and disk.</li>"
            "<li><b>Load Full History</b>: load all archived records for viewing.</li>"
            "<li><b>Set Category</b>: assign the host to a category or create a new one.</li>"
            "<li><b>Rename (F2)</b>: the history directory is moved together with the host.</li>"
            "<li><b>Drag &amp; drop</b>: reorder hosts inside a category or move them between categories.</li>"
            "<li><b>Search</b>: filter the host list by substring. Combined with the active filter mode.</li>"
            "</ul>")

        + _("<h3>Filter modes</h3>"
            "<p>The filter button (in the toolbar) cycles through: "
            "<b>All</b> → <b>Failed</b> → <b>Warn</b> → <b>Disabled</b>.</p>"
            "<ul>"
            "<li><b>All</b> — show every host.</li>"
            "<li><b>Failed</b> — only hosts with consecutive failures ≥ alert threshold.</li>"
            "<li><b>Warn</b> — only hosts with 1 ≤ failures &lt; alert threshold.</li>"
            "<li><b>Disabled</b> — only disabled or muted hosts.</li>"
            "</ul>"
            "<p>You can also click the <b>Warn</b>, <b>Down</b> or <b>Disabled</b> counter in the summary bar "
            "to switch to that filter in one click. Click the active counter again to return to <b>All</b>.</p>")

        + _("<h3>Graphs</h3>"
            "<p>Solid bars represent each check (green = success, red = failure). "
            "When <b>Show latency scale</b> is enabled, bars grow from the baseline up to the "
            "measured latency and a thin line connects the tops of successful checks. "
            "Long pauses between checks are left blank so it is clear that no monitoring took place.</p>"
            "<ul>"
            "<li><b>Graph height</b>: Compact (50 px) / Normal (80 px) / Expanded (200 px). "
            "Change it in Settings → General, via Ctrl+R, or from the right-click menu on any graph.</li>"
            "<li><b>Zoom</b>: scroll wheel over the time scale — zoom in/out around the cursor.</li>"
            "<li><b>Select period</b>: drag on the time scale to zoom into that range.</li>"
            "<li><b>Reset zoom</b>: right-click on the time scale.</li>"
            "<li><b>Prioritize</b>: double-click a graph to move that host to the front of the queue.</li>"
            "<li><b>Right-click</b> on a graph — same context menu as on the tree.</li>"
            "</ul>")

        + _("<h3>Batch fping</h3>"
            "<p>If <code>fping</code> is installed, ICMP hosts are checked in batches "
            "of the size configured in Settings → General. On each timer tick a batch of ICMP hosts "
            "and one TCP host are checked.</p>")

        + _("<h3>Alerts and notifications</h3>"
            "<p>Threshold, reminder interval and recovery notifications are configured in "
            "Application → Settings → Alerts.</p>"
            "<p>Tray notifications are grouped within a 2-second window: if several hosts go down "
            "at the same time, you receive a single aggregated notification "
            "(e.g. &quot;5 hosts are not responding&quot;).</p>"
            "<p>The tray icon shows a red badge with the number of currently failed hosts. "
            "A yellow icon indicates that at least one host is in the warning state.</p>")

        + _("<h3>Appearance</h3>"
            "<p>In Settings → General you can choose <b>Auto</b> (follow the system theme), "
            "<b>Light</b> or <b>Dark</b>. In Auto mode the theme is switched automatically when the "
            "system color scheme changes.</p>")

        + _("<h3>Language</h3>"
            "<p>The Language menu is built automatically from the compiled translations "
            "available under <code>translations/&lt;code&gt;/LC_MESSAGES/qping.mo</code>. "
            "To add a new language, place the compiled <code>.mo</code> file in the appropriate folder — "
            "no code change is needed.</p>")

        + _("<h3>Storage</h3>"
            "<p>History: <code>~/.config/QPing/history/&lt;host&gt;/YYYY-MM-DD.jsonl</code>.<br>"
            "Only the last hour is loaded on startup; older days are fetched on demand when you scroll "
            "the time scale into the past.<br>"
            "Auto-cleanup is configured in Application → Settings → Storage.</p>")

        + _("<h3>Hooks</h3>"
            "<p>External scripts triggered on host down/up transitions. "
            "See Settings → Hooks. Environment variables passed to the scripts: "
            "<code>QPING_HOST</code>, <code>QPING_STATUS</code> (down/up), "
            "<code>QPING_FAILURES</code>, <code>QPING_TIMESTAMP</code>.</p>")

        + _("<h3>Ansible inventory import</h3>"
            "<p>Import → select <code>.ini</code> or <code>.yml</code>/<code>.yaml</code>. "
            "Groups become categories; <code>ansible_host</code> overrides the inventory hostname.</p>")

        + _("<h3>Backup and restore</h3>"
            "<p>Application → Export Hosts saves the full list (hosts, categories, check types, "
            "disabled and muted flags) into a <code>.qping.json</code> file. "
            "Import with the same extension restores or merges the list.</p>")
    )
