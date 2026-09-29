# theme.py
"""
QPing theme: light/dark palettes + applying them to QApplication.

Usage:
    from theme import palette, apply_theme, detect_system
    apply_theme(QApplication.instance(), "auto")  # 'auto' | 'light' | 'dark'
    p = palette()
    p.graph_ok  # QColor
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QPalette
from PyQt6.QtWidgets import QApplication


class Palette:
    def __init__(self, name, **kw):
        self.name = name
        self.__dict__.update(kw)


# ---------- Light ----------

LIGHT = Palette(
    name="light",
    # text
    text=QColor("#1a1a1a"),
    text_dim=QColor("#666666"),
    text_muted=QColor("#888888"),
    text_disabled=QColor("#9e9e9e"),
    # statuses (summary)
    color_ok=QColor("#2E7D32"),
    color_warn=QColor("#EF6C00"),
    color_down=QColor("#C62828"),
    # host colors in the tree
    host_normal=QColor("#1a1a1a"),
    host_warn=QColor("#EF6C00"),
    host_down=QColor("#C62828"),
    host_muted=QColor("#888888"),
    host_disabled=QColor("#9e9e9e"),
    # surfaces
    category_bg=QColor("#E0E0E0"),
    highlight_bg=QColor("#ADD8E6"),
    clear_bg=QColor("#ffffff"),
    # graphs
    graph_ok=QColor("#81C784"),
    graph_fail=QColor("#E57373"),
    graph_grid=QColor("#BDBDBD"),
    graph_axis=QColor("#757575"),
    graph_avg=QColor(90, 90, 90, 210),
    graph_hover=QColor(60, 60, 60, 160),
    graph_bg=QColor("#fafafa"),
    # time scale
    time_axis=QColor("#333333"),
    drag_fill=QColor(30, 120, 200, 60),
    drag_stroke=QColor(30, 120, 200, 200),
)

# ---------- Dark ----------

DARK = Palette(
    name="dark",
    text=QColor("#e0e0e0"),
    text_dim=QColor("#a0a0a0"),
    text_muted=QColor("#9e9e9e"),
    text_disabled=QColor("#6e6e6e"),
    color_ok=QColor("#66BB6A"),
    color_warn=QColor("#FFA726"),
    color_down=QColor("#EF5350"),
    host_normal=QColor("#e0e0e0"),
    host_warn=QColor("#FFA726"),
    host_down=QColor("#EF5350"),
    host_muted=QColor("#9e9e9e"),
    host_disabled=QColor("#6e6e6e"),
    category_bg=QColor("#3a3a3a"),
    highlight_bg=QColor("#2c4a6e"),
    clear_bg=QColor("#2b2b2b"),
    graph_ok=QColor("#66BB6A"),
    graph_fail=QColor("#EF5350"),
    graph_grid=QColor("#4a4a4a"),
    graph_axis=QColor("#8a8a8a"),
    graph_avg=QColor(225, 225, 225, 200),
    graph_hover=QColor(230, 230, 230, 170),
    graph_bg=QColor("#1e1e1e"),
    time_axis=QColor("#cfcfcf"),
    drag_fill=QColor(80, 160, 240, 70),
    drag_stroke=QColor(80, 160, 240, 220),
)


_active = LIGHT


def palette():
    """Return the current active palette."""
    return _active


def set_active(name):
    global _active
    _active = DARK if name == "dark" else LIGHT


def detect_system():
    """Return 'dark' or 'light' from the system color scheme / palette."""
    app = QApplication.instance()
    if app is None:
        return "light"
    try:
        sh = app.styleHints()
        if hasattr(sh, "colorScheme"):
            scheme = sh.colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return "dark"
            if scheme == Qt.ColorScheme.Light:
                return "light"
    except Exception:
        pass
    p = app.palette()
    c = p.color(QPalette.ColorRole.Window)
    return "dark" if c.lightness() < 128 else "light"


def _dark_palette():
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor("#2b2b2b"))
    p.setColor(QPalette.ColorRole.WindowText, QColor("#e0e0e0"))
    p.setColor(QPalette.ColorRole.Base, QColor("#1e1e1e"))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor("#262626"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor("#2b2b2b"))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor("#e0e0e0"))
    p.setColor(QPalette.ColorRole.Text, QColor("#e0e0e0"))
    p.setColor(QPalette.ColorRole.Button, QColor("#3a3a3a"))
    p.setColor(QPalette.ColorRole.ButtonText, QColor("#e0e0e0"))
    p.setColor(QPalette.ColorRole.BrightText, QColor("#FF5252"))
    p.setColor(QPalette.ColorRole.Link, QColor("#64B5F6"))
    p.setColor(QPalette.ColorRole.Highlight, QColor("#3d6fa5"))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor("#6e6e6e"))
    p.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor("#6e6e6e"))
    return p


def apply_theme(app, name):
    """Apply the QApplication palette and set the active internal palette.
    name: 'auto' | 'light' | 'dark'. Returns the resolved name."""
    if app is None:
        return "light"
    resolved = detect_system() if name == "auto" else name
    set_active(resolved)
    if resolved == "dark":
        app.setPalette(_dark_palette())
    else:
        app.setPalette(app.style().standardPalette())
    return resolved
