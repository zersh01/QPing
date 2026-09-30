# main.py
"""
QPing — main window. Run

"""
APP_VERSION = "2.4"

import sys
import json
import os
import shutil
import subprocess
import gzip

from datetime import datetime, timedelta
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QTreeWidget,
    QTreeWidgetItem, QLineEdit, QLabel, QMessageBox, QInputDialog, QSlider,
    QScrollArea, QFrame, QMenu, QPushButton, QSystemTrayIcon,
    QFileDialog, QDialog, QComboBox, QDialogButtonBox, QTextEdit,
    QSpinBox, QFormLayout, QCheckBox, QTabWidget, QGraphicsOpacityEffect,
    QStyle
)
from PyQt6.QtCore import (
    Qt, QSettings, QTimer, QThreadPool, QPropertyAnimation,
    QEasingCurve, pyqtSignal, pyqtSlot, QObject, QRunnable, QPoint
)
from PyQt6.QtGui import (
    QColor, QFont, QIcon, QPixmap, QAction, QActionGroup,
    QKeySequence, QPainter, QFontMetrics
)

from ping_manager import PingManager, PingWorker, has_fping
from ping_widgets import TimeScaleWidget, HostWidget, PingGraphWidget
from theme import palette, apply_theme
from utils import (
    CONFIG_DIR, HISTORY_DIR, HOOKS_DIR_DEFAULT,
    setup_localization, read_bool_setting, read_int_setting, host_safe_name,
    detect_import_format, parse_ansible_ini, parse_ansible_yaml,
    parse_hosts_file, parse_plain_list, parse_backup, build_backup,
    discover_languages,
)


class ClickableLabel(QLabel):
    """QLabel that reacts to a left mouse click. Signal `clicked`."""

    clicked = pyqtSignal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
            return
        super().mousePressEvent(event)


# ---------- Asynchronous save ----------

class _SaveSignals(QObject):
    finished = pyqtSignal(dict)


class SaveWorker(QRunnable):
    def __init__(self, snapshot):
        super().__init__()
        self.snapshot = snapshot
        self.signals = _SaveSignals()

    @pyqtSlot()
    def run(self):
        result = {}
        for host, data in self.snapshot.items():
            latest = None
            try:
                host_dir = data['dir']
                os.makedirs(host_dir, exist_ok=True)
                with open(os.path.join(host_dir, "meta.json"), 'w') as mf:
                    json.dump(data['meta'], mf, indent=2)
                by_day = {}
                for t, s, lat in data['records']:
                    key = t.strftime("%Y-%m-%d")
                    by_day.setdefault(key, []).append((t, s, lat))
                    if latest is None or t > latest:
                        latest = t
                for day, recs in by_day.items():
                    path = os.path.join(host_dir, f"{day}.jsonl")
                    with open(path, 'a') as f:
                        for t, s, lat in recs:
                            f.write(json.dumps([t.isoformat(), s, lat]) + "\n")
                result[host] = latest
            except Exception as e:
                print(f"[save] error for {host}: {e}")
                result[host] = None
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            pass


# ---------- Hooks ----------

class HookWorker(QRunnable):
    def __init__(self, script_path, env_vars):
        super().__init__()
        self.script_path = script_path
        self.env_vars = env_vars

    @pyqtSlot()
    def run(self):
        try:
            env = os.environ.copy()
            env.update(self.env_vars)
            subprocess.run(
                [self.script_path],
                timeout=30,
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except Exception as e:
            print(f"[hook] {self.script_path}: {e}")


# ---------- Per-day history loading ----------

def list_history_days(host_dir):
    try:
        entries = os.listdir(host_dir)
    except Exception:
        return []
    days = []
    for fname in entries:
        if not fname.endswith(".jsonl"):
            continue
        day_str = fname[:-6]
        try:
            datetime.strptime(day_str, "%Y-%m-%d")
        except ValueError:
            continue
        days.append(day_str)
    days.sort()
    return days


def read_history_days(host_dir, day_strs):
    records = []
    latest_time = None
    for day_str in day_strs:
        path = os.path.join(host_dir, f"{day_str}.jsonl")
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        parsed = json.loads(line)
                        t = datetime.fromisoformat(parsed[0])
                        s = bool(parsed[1])
                        lat = float(parsed[2]) if len(parsed) > 2 else (-1.0 if not s else 0.0)
                    except Exception:
                        continue
                    records.append((t, s, lat))
                    if latest_time is None or t > latest_time:
                        latest_time = t
        except Exception as e:
            print(f"Error reading {path}: {e}")
    records.sort(key=lambda x: x[0])
    return records, latest_time


def _days_between(start_dt, end_dt):
    days = set()
    d = start_dt.date()
    last = end_dt.date()
    while d <= last:
        days.add(d.strftime("%Y-%m-%d"))
        d += timedelta(days=1)
    return days


class _DayLoadSignals(QObject):
    finished = pyqtSignal(dict)


class DayLoadWorker(QRunnable):
    def __init__(self, host_dirs, host_days):
        super().__init__()
        self.host_dirs = dict(host_dirs)
        self.host_days = {h: list(d) for h, d in host_days.items()}
        self.signals = _DayLoadSignals()

    @pyqtSlot()
    def run(self):
        result = {}
        for host, hd in self.host_dirs.items():
            days = self.host_days.get(host, [])
            records, latest = read_history_days(hd, days)
            result[host] = {
                'days_loaded': days,
                'records': records,
                'latest_time': latest,
            }
        try:
            self.signals.finished.emit(result)
        except RuntimeError:
            pass


# ---------- Main window ----------

class PingMonitor(QMainWindow):
    def __init__(self):
        super().__init__()
        os.makedirs(CONFIG_DIR, exist_ok=True)
        os.makedirs(HISTORY_DIR, exist_ok=True)
        os.makedirs(HOOKS_DIR_DEFAULT, exist_ok=True)

        self.settings = QSettings("QPing", "QPing")

        # --- Theme and appearance ---
        self.appearance = self.settings.value("appearance", "auto")
        self.graph_show_latency = read_bool_setting(self.settings, "graph_show_latency", True)
        self.graph_height_mode = self.settings.value("graph_height_mode", "normal")
        if self.graph_height_mode not in ("compact", "normal", "expanded"):
            self.graph_height_mode = "normal"
        self._resolved_theme = apply_theme(QApplication.instance(), self.appearance)

        self._color_scheme_hooked = False
        try:
            sh = QApplication.instance().styleHints()
            if hasattr(sh, "colorSchemeChanged"):
                sh.colorSchemeChanged.connect(self._on_color_scheme_changed)
                self._color_scheme_hooked = True
        except Exception:
            pass

        self.language = self.settings.value("language", "ru")
        self._ = setup_localization(self.language)
        self.setWindowTitle(self._("QPing Monitor"))
        self.setGeometry(100, 100, 1200, 700)

        self.app_start_time = datetime.now()
        self.notifications_enabled = read_bool_setting(self.settings, "notifications_enabled", True)
        self.is_quitting = False
        # filter_mode: 'all' | 'failed' | 'warn' | 'disabled'
        self.filter_mode = self.settings.value("filter_mode", None)
        if self.filter_mode not in ("all", "failed", "warn", "disabled"):
            self.filter_mode = "failed" if read_bool_setting(
                self.settings, "filter_failed", False) else "all"
        self.minimize_on_escape = read_bool_setting(self.settings, "minimize_on_escape", True)

        self.retention_hours = max(1, read_int_setting(self.settings, "retention_hours", 48))

        self.alerts_after_failures = max(1, read_int_setting(self.settings, "alerts_after_failures", 2))
        self.alert_reminder_minutes = max(1, read_int_setting(self.settings, "alert_reminder_minutes", 5))
        self.notify_on_recovery = read_bool_setting(self.settings, "notify_on_recovery", True)

        self.cleanup_enabled = read_bool_setting(self.settings, "cleanup_enabled", False)
        self.cleanup_days = max(1, read_int_setting(self.settings, "cleanup_days", 30))

        self.hooks_enabled = read_bool_setting(self.settings, "hooks_enabled", False)
        self.hooks_dir = self.settings.value("hooks_dir", HOOKS_DIR_DEFAULT, type=str) or HOOKS_DIR_DEFAULT
        os.makedirs(self.hooks_dir, exist_ok=True)

        self.fping_batch_size = max(1, read_int_setting(self.settings, "fping_batch_size", 5))
        self.ping_timeout_ms = max(0, read_int_setting(self.settings, "ping_timeout_ms", 0))

        self.search_text = ""

        self.categories_list = self.settings.value("categories", ["Default"], type=list)
        if "Default" not in self.categories_list:
            self.categories_list.append("Default")

        self.green_icon = self.create_icon("#4CAF50")
        self.yellow_icon = self.create_icon("#FFEB3B")
        self.red_icon = self.create_icon("#F44336")
        self.setWindowIcon(self.green_icon)
        self._current_icon = self.green_icon

        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.green_icon)
        self.tray_icon.setVisible(True)
        self.tray_icon.activated.connect(self.tray_icon_activated)

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowTitleHint
            | Qt.WindowType.WindowSystemMenuHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowMaximizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )

        self.host_widgets = {}
        self.host_check_types = {}
        self.highlight_animation = None

        self.icmp_queue = []
        self.tcp_queue = []
        self.icmp_idx = 0
        self.tcp_idx = 0
        self._highlighted_hosts = []
        self._focused_host = None

        self.parking_widget = QWidget()
        self.parking_widget.hide()

        self.time_scale = TimeScaleWidget(self)
        self.time_scale.set_left_gutter(
            PingGraphWidget.LEFT_GUTTER if self.graph_show_latency else 0
        )
        self.time_scale.zoom_changed.connect(self.update_all_graphs)
        self.time_scale.zoom_changed.connect(self.on_zoom_changed)

        self.host_list = QTreeWidget()
        self.host_list.setHeaderHidden(True)
        self.host_list.setDragDropMode(QTreeWidget.DragDropMode.InternalMove)
        self.host_list.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        self.host_list.setDragEnabled(True)
        self.host_list.setAcceptDrops(True)
        self.host_list.setDropIndicatorShown(True)
        self.host_list.itemDoubleClicked.connect(self.scroll_to_host_widget)
        self.host_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.host_list.customContextMenuRequested.connect(self.show_host_context_menu)
        self.host_list.itemSelectionChanged.connect(self._on_host_selection_changed)
        self.host_list.model().rowsMoved.connect(self.handle_host_moved)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)

        saved_interval = read_int_setting(self.settings, "interval", 500)

        self.thread_pool = QThreadPool()
        self.thread_pool.setMaxThreadCount(10)
        self.hook_pool = QThreadPool()
        self.hook_pool.setMaxThreadCount(2)

        self._save_in_progress = False
        self._save_workers = set()
        self._history_loading_in_progress = False
        self._pending_days = {}

        # --- Notifications: group within a 2-second window ---
        self._notify_queue = []
        self._notify_timer = QTimer(self)
        self._notify_timer.setSingleShot(True)
        self._notify_timer.setInterval(2000)
        self._notify_timer.timeout.connect(self._flush_notifications)

        self._icon_cache = {}

        self.ping_manager = PingManager(saved_interval, self.thread_pool, self.ping_timeout_ms)
        self.ping_manager.ping_result.connect(self.handle_ping_result)

        self.ping_timer = QTimer()
        self.ping_timer.timeout.connect(self.ping_tick)

        self.autosave_timer = QTimer()
        self.autosave_timer.timeout.connect(self.save_data)
        self.autosave_timer.start(60000)

        self.slide_timer = QTimer()
        self.slide_timer.timeout.connect(self.time_scale.auto_slide)
        self.slide_timer.start(1000)

        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self.run_auto_cleanup)
        self.cleanup_timer.start(24 * 60 * 60 * 1000)

        self.setup_ui()
        QTimer.singleShot(0, self.load_data)
        self.interval_slider.setValue(saved_interval)
        self.update_interval(saved_interval)
        self.time_scale.reset_zoom()

        if self.cleanup_enabled:
            QTimer.singleShot(5000, self.run_auto_cleanup)

    # ---------- Theme ----------

    def _apply_summary_styles(self):
        p = palette()
        self.lbl_ok.setStyleSheet(f"color: {p.color_ok.name()}; font-weight: bold;")
        self.lbl_engine.setStyleSheet(f"color: {p.text_dim.name()};")

        warn_style = f"color: {p.color_warn.name()}; font-weight: bold;"
        if self.filter_mode == "warn":
            warn_style += " text-decoration: underline;"
        self.lbl_warn.setStyleSheet(warn_style)

        down_style = f"color: {p.color_down.name()}; font-weight: bold;"
        if self.filter_mode == "failed":
            down_style += " text-decoration: underline;"
        self.lbl_down.setStyleSheet(down_style)

        disabled_style = f"color: {p.text_disabled.name()};"
        if self.filter_mode == "disabled":
            disabled_style += " text-decoration: underline;"
        self.lbl_disabled.setStyleSheet(disabled_style)

        for lbl in (self.lbl_warn, self.lbl_down, self.lbl_disabled):
            lbl.setCursor(Qt.CursorShape.PointingHandCursor)

    def _recolor_tree(self):
        """Recolor the tree without a full rebuild (preserves selection).
        Updates both the category backgrounds and the background/text of all
        hosts to match the current palette."""
        p = palette()
        highlighted = set(self._highlighted_hosts)
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            ci.setBackground(0, p.category_bg)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                host = hi.data(0, Qt.ItemDataRole.UserRole)
                hi.setBackground(0, p.highlight_bg if host in highlighted else p.clear_bg)
                w = self.host_widgets.get(host)
                if w:
                    hi.setForeground(0, self._host_color(w))

    def apply_appearance(self, name):
        self.appearance = name
        self._resolved_theme = apply_theme(QApplication.instance(), name)
        self.settings.setValue("appearance", name)
        self._apply_summary_styles()
        self._recolor_tree()
        for w in self.host_widgets.values():
            w.update_host_label()
            w.graph_widget.update()
        self.update_all_graphs()

    def apply_graph_height(self, mode):
        """Set and persist the graph height mode for all graphs."""
        if mode not in ("compact", "normal", "expanded"):
            mode = "normal"
        self.graph_height_mode = mode
        self.settings.setValue("graph_height_mode", mode)
        for w in self.host_widgets.values():
            w.graph_widget.set_graph_height_mode(mode)

    def _on_color_scheme_changed(self, _scheme):
        if self.appearance == "auto":
            self.apply_appearance("auto")

    # ---------- Keyboard ----------

    def keyPressEvent(self, event):
        key = event.key()
        mods = event.modifiers()
        if key == Qt.Key.Key_Escape:
            fw = QApplication.focusWidget()
            if isinstance(fw, QLineEdit) and fw.text():
                fw.clear()
                event.accept()
                return
            if self.minimize_on_escape:
                self.hide()
                event.accept()
                return
        if key == Qt.Key.Key_Delete:
            self._on_delete_shortcut()
            event.accept()
            return
        if key == Qt.Key.Key_F2:
            self._on_f2_shortcut()
            event.accept()
            return
        if key == Qt.Key.Key_F and (mods & Qt.KeyboardModifier.ControlModifier):
            self.search_input.setFocus()
            self.search_input.selectAll()
            event.accept()
            return
        if key == Qt.Key.Key_R and (mods & Qt.KeyboardModifier.ControlModifier):
            order = ["compact", "normal", "expanded"]
            i = order.index(self.graph_height_mode) if self.graph_height_mode in order else 1
            self.apply_graph_height(order[(i + 1) % len(order)])
            event.accept()
            return
        if key == Qt.Key.Key_N and (mods & Qt.KeyboardModifier.ControlModifier):
            self.host_input.setFocus()
            self.host_input.selectAll()
            event.accept()
            return
        super().keyPressEvent(event)

    def _on_delete_shortcut(self):
        sel = [i for i in self.host_list.selectedItems() if i.parent() is not None]
        hosts = [i.data(0, Qt.ItemDataRole.UserRole) for i in sel]
        if hosts:
            self.delete_hosts(hosts)

    def _on_f2_shortcut(self):
        sel = [i for i in self.host_list.selectedItems() if i.parent() is not None]
        if len(sel) == 1:
            self.edit_host(sel[0].data(0, Qt.ItemDataRole.UserRole))

    # ---------- Paths / icon ----------

    def _host_dir(self, host):
        return os.path.join(HISTORY_DIR, host_safe_name(host))

    def _make_host_widget(self, host, category):
        """Create a HostWidget with the current settings applied."""
        w = HostWidget(host, self.time_scale, self.app_start_time, category)
        w.retention_hours = self.retention_hours
        w.graph_widget.set_show_latency(self.graph_show_latency)
        w.graph_widget.set_check_interval(self.interval_slider.value())
        w.graph_widget.set_graph_height_mode(self.graph_height_mode)
        w.context_menu_requested.connect(self._on_host_context_menu_from_graph)
        return w

    def create_icon(self, color):
        icon = QIcon()
        for size in (16, 22, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            margin = max(1, size // 16)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(margin, margin,
                                size - 2 * margin, size - 2 * margin)
            if size >= 22:
                painter.setPen(QColor("white"))
                font = QFont("Arial", int(size * 0.6), QFont.Weight.Bold)
                painter.setFont(font)
                painter.drawText(pixmap.rect(),
                                 Qt.AlignmentFlag.AlignCenter, "Q")
            painter.end()
            icon.addPixmap(pixmap)
        return icon

    # ---------- Window ----------

    def quit_application(self):
        self.is_quitting = True
        self._save_data_sync()
        QApplication.quit()

    def closeEvent(self, event):
        if self.is_quitting:
            event.accept()
        else:
            self.save_data()
            event.ignore()
            self.hide()

    def restore_window(self):
        if self.isMinimized():
            self.showNormal()
        else:
            self.show()
        self.setWindowState(
            (self.windowState() & ~Qt.WindowState.WindowMinimized)
            | Qt.WindowState.WindowActive
        )
        self.raise_()
        self.activateWindow()

    def tray_icon_activated(self, reason):
        if reason in (QSystemTrayIcon.ActivationReason.DoubleClick,
                      QSystemTrayIcon.ActivationReason.Trigger):
            self.restore_window()

    # ---------- Navigation / drag ----------

    def scroll_to_host_widget(self, item, column):
        host = item.data(0, Qt.ItemDataRole.UserRole)
        if host and host in self.host_widgets:
            self._focused_host = host
            widget = self.host_widgets[host]
            self.scroll_area.ensureWidgetVisible(widget)
            self.start_highlight_animation(widget)

    def start_highlight_animation(self, widget):
        if self.highlight_animation:
            self.highlight_animation.stop()
        effect = QGraphicsOpacityEffect(widget)
        widget.setGraphicsEffect(effect)
        self.highlight_animation = QPropertyAnimation(effect, b"opacity")
        self.highlight_animation.setDuration(1000)
        self.highlight_animation.setLoopCount(2)
        self.highlight_animation.setStartValue(0.3)
        self.highlight_animation.setEndValue(1.0)
        self.highlight_animation.setEasingCurve(QEasingCurve.Type.OutQuad)
        self.highlight_animation.start()

        def cleanup():
            widget.setGraphicsEffect(None)
            self.highlight_animation = None
        self.highlight_animation.finished.connect(cleanup)

    def handle_host_moved(self, parent, start, end, destination, row):
        QTimer.singleShot(0, self._finalize_host_moved)

    def _finalize_host_moved(self):
        for i in range(self.host_list.topLevelItemCount()):
            cat_item = self.host_list.topLevelItem(i)
            cat_name = cat_item.data(0, Qt.ItemDataRole.UserRole)
            for j in range(cat_item.childCount()):
                child_item = cat_item.child(j)
                host_name = child_item.data(0, Qt.ItemDataRole.UserRole)
                if host_name in self.host_widgets:
                    self.host_widgets[host_name].category = cat_name

        new_order = {}
        for i in range(self.host_list.topLevelItemCount()):
            cat_item = self.host_list.topLevelItem(i)
            for j in range(cat_item.childCount()):
                child_item = cat_item.child(j)
                h = child_item.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    new_order[h] = self.host_widgets[h]
        for h, w in self.host_widgets.items():
            if h not in new_order:
                new_order[h] = w
        self.host_widgets = new_order

        self.update_host_queue()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()

    def _update_tree_width(self):
        """Lock the hosts panel width to the longest string + padding.
        QFontMetrics and sizeHintForColumn(0) underestimate the actual text
        width on some fonts/DPI, so we add 15% + 12 px."""
        fm = self.host_list.fontMetrics()

        # Temporarily show all items so the width does not jump while filtering.
        hidden_cats, hidden_items = [], []
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            if ci.isHidden():
                hidden_cats.append(ci)
                ci.setHidden(False)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.isHidden():
                    hidden_items.append(hi)
                    hi.setHidden(False)

        try:
            # Manual measurement per row
            max_text_w = 0
            for i in range(self.host_list.topLevelItemCount()):
                ci = self.host_list.topLevelItem(i)
                max_text_w = max(max_text_w, fm.horizontalAdvance(ci.text(0)))
                for j in range(ci.childCount()):
                    hi = ci.child(j)
                    max_text_w = max(max_text_w, fm.horizontalAdvance(hi.text(0)))

            hint_w = self.host_list.sizeHintForColumn(0)
        finally:
            for ci in hidden_cats:
                ci.setHidden(True)
            for hi in hidden_items:
                hi.setHidden(True)

        if max_text_w <= 0:
            max_text_w = fm.horizontalAdvance("example.com [p:65535]")

        # QFontMetrics underestimates: +15% and at least +12 px.
        # Take the maximum of three estimates so it's always enough.
        safe_text_w = max(
            int(max_text_w * 1.15) + 12,
            hint_w,
            max_text_w + 20,
        )

        indent = self.host_list.indentation()      # indent for children
        icon = 18                                   # expansion icon
        delegate_pad = 8                            # delegate padding
        item_area = safe_text_w + indent + icon + delegate_pad

        scrollbar = self.host_list.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent)
        frame = 2 * self.host_list.frameWidth()
        extra = 5

        tree_w = item_area + scrollbar + frame + extra

        # Minimum width — enough for the search box and both "+"/"−" buttons
        search_min = (self.search_input.minimumSizeHint().width()
                      + self.expand_all_btn.width()
                      + self.collapse_all_btn.width()
                      + 20)
        total = max(tree_w, search_min)

        # Upper bound — no more than 45% of the window width to save room for graphs
        if self.width() > 0:
            total = min(total, int(self.width() * 0.45))

        self.left_panel.setFixedWidth(total)

    # ---------- Layout ----------

    def add_category_separator(self, category):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        label = QLabel(f"[{category}]")
        label.setFont(QFont("Arial", 10, QFont.Weight.Bold))
        label.setStyleSheet("padding: 5px;")
        c = QWidget()
        cl = QHBoxLayout()
        cl.addWidget(label)
        cl.addWidget(sep)
        c.setLayout(cl)
        return c

    def reorder_graphs(self):
        while self.right_panel_layout.count() > 0:
            item = self.right_panel_layout.takeAt(0)
            w = item.widget()
            if w:
                w.setParent(self.parking_widget)
        for category in self.sorted_categories():
            cat_widgets = [w for w in self.host_widgets.values() if w.category == category]
            has_visible = False
            if self.filter_mode == "failed":
                has_visible = any(
                    (w.consecutive_failures >= self.alerts_after_failures)
                    for w in cat_widgets if not w.disabled
                )
            elif self.filter_mode == "warn":
                has_visible = any(
                    (1 <= w.consecutive_failures < self.alerts_after_failures)
                    for w in cat_widgets if not w.disabled
                )
            elif self.filter_mode == "disabled":
                has_visible = any(
                    (w.disabled or w.muted) for w in cat_widgets
                )
            else:
                has_visible = True
            if not has_visible:
                continue
            self.right_panel_layout.addWidget(self.add_category_separator(category))

            def traverse(parent_item):
                for i in range(parent_item.childCount()):
                    child = parent_item.child(i)
                    host = child.data(0, Qt.ItemDataRole.UserRole)
                    if host and host in self.host_widgets and self.host_widgets[host].category == category:
                        w = self.host_widgets[host]
                        if self.filter_mode == "all":
                            self.right_panel_layout.addWidget(w)
                        else:
                            if self._host_should_show(w, host):
                                self.right_panel_layout.addWidget(w)
            for i in range(self.host_list.topLevelItemCount()):
                ci = self.host_list.topLevelItem(i)
                if ci.data(0, Qt.ItemDataRole.UserRole) == category:
                    traverse(ci)

    def move_host_to_queue_start(self, host):
        if host in self.icmp_queue:
            self.icmp_queue.remove(host)
            self.icmp_queue.insert(0, host)
            self.icmp_idx = 0
        elif host in self.tcp_queue:
            self.tcp_queue.remove(host)
            self.tcp_queue.insert(0, host)
            self.tcp_idx = 0
        self.ping_tick()

    # ---------- UI ----------

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout()
        central.setLayout(layout)

        menu_bar = self.menuBar()

        self.menu_app = menu_bar.addMenu(self._("Application"))

        self.action_settings = QAction(self._("Settings..."), self)
        self.action_settings.triggered.connect(self.show_settings_dialog)
        self.menu_app.addAction(self.action_settings)

        self.action_export = QAction(self._("Export Hosts..."), self)
        self.action_export.triggered.connect(self.export_hosts_to_file)
        self.menu_app.addAction(self.action_export)

        self.action_import = QAction(self._("Import Hosts..."), self)
        self.action_import.triggered.connect(self.import_hosts_from_file)
        self.menu_app.addAction(self.action_import)

        self.menu_app.addSeparator()

        self.action_close = QAction(self._("Close"), self)
        self.action_close.setShortcut(QKeySequence("Ctrl+W"))
        self.action_close.triggered.connect(self.close)
        self.menu_app.addAction(self.action_close)

        self.menu_app.addSeparator()

        self.action_quit = QAction(self._("Quit"), self)
        self.action_quit.setShortcut(QKeySequence("Ctrl+Q"))
        self.action_quit.triggered.connect(self.quit_application)
        self.menu_app.addAction(self.action_quit)

        # --- Help ---
        self.menu_help = menu_bar.addMenu(self._("Help"))
        self.action_help = QAction(self._("User Guide"), self)
        self.action_help.triggered.connect(self.show_help)
        self.menu_help.addAction(self.action_help)

        self.action_about = QAction(self._("About"), self)
        self.action_about.triggered.connect(self.show_about)
        self.menu_help.addAction(self.action_about)

        # --- Language ---
        # The language list is built automatically from
        # translations/<code>/LC_MESSAGES/qping.mo.
        # To add a new language, just drop the compiled .mo file in place.
        self.menu_lang = menu_bar.addMenu(self._("Language"))
        self._lang_actions = {}                      # {code: QAction}
        self._lang_group = QActionGroup(self)
        self._lang_group.setExclusive(True)
        for code, display in discover_languages():
            a = QAction(display, self)
            a.setCheckable(True)
            a.setChecked(code == self.language)
            a.triggered.connect(lambda _checked=False, c=code: self.change_language(c))
            self._lang_group.addAction(a)
            self.menu_lang.addAction(a)
            self._lang_actions[code] = a

        # --- Tray menu ---
        self.tray_menu = QMenu()
        self.tray_action_restore = QAction(self._("Restore"), self)
        self.tray_action_restore.triggered.connect(self.restore_window)
        self.tray_menu.addAction(self.tray_action_restore)
        self.tray_action_quit = QAction(self._("Quit"), self)
        self.tray_action_quit.triggered.connect(self.quit_application)
        self.tray_menu.addAction(self.tray_action_quit)
        self.tray_icon.setContextMenu(self.tray_menu)

        # --- Control panel ---
        control_panel = QWidget()
        cl = QHBoxLayout()
        control_panel.setLayout(cl)
        self.host_input = QLineEdit(placeholderText=self._("Enter IP/domain"))
        self.host_input.returnPressed.connect(self.add_host)
        self.add_button = QPushButton(self._("Add Host"))
        self.add_button.clicked.connect(self.add_host)
        self.import_button = QPushButton(self._("Import from File"))
        self.import_button.clicked.connect(self.import_hosts_from_file)
        self.interval_slider = QSlider(Qt.Orientation.Horizontal)
        self.interval_slider.setRange(100, 5000)
        self.interval_slider.setTickInterval(100)
        self.interval_slider.valueChanged.connect(self.update_interval)
        self.interval_label = QLabel(self._("Interval: {}ms").format(self.interval_slider.value()))
        self.mute_button = QPushButton(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self.mute_button.clicked.connect(self.toggle_notifications)
        self.filter_button = QPushButton()
        self.filter_button.setToolTip(self._("Cycle filter: All → Failed → Warn"))
        self.filter_button.clicked.connect(self.toggle_filter)
        self._update_filter_button_text()
        self.interval_caption = QLabel(self._("Interval:"))
        cl.addWidget(self.host_input)
        cl.addWidget(self.add_button)
        cl.addWidget(self.import_button)
        cl.addWidget(self.interval_caption)
        cl.addWidget(self.interval_slider)
        cl.addWidget(self.interval_label)
        cl.addWidget(self.mute_button)
        cl.addWidget(self.filter_button)

        # --- Summary panel ---
        summary_panel = QFrame()
        summary_panel.setFrameShape(QFrame.Shape.StyledPanel)
        sl = QHBoxLayout()
        sl.setContentsMargins(6, 2, 6, 2)
        summary_panel.setLayout(sl)
        self.lbl_total = QLabel("Total: 0")
        self.lbl_ok = QLabel("OK: 0")
        self.lbl_warn = ClickableLabel("Warn: 0")
        self.lbl_warn.setToolTip(self._("Click to show only warning hosts"))
        self.lbl_warn.clicked.connect(lambda: self.toggle_summary_filter("warn"))
        self.lbl_down = ClickableLabel("Down: 0")
        self.lbl_down.setToolTip(self._("Click to show only down hosts"))
        self.lbl_down.clicked.connect(lambda: self.toggle_summary_filter("failed"))
        self.lbl_disabled = ClickableLabel("Disabled: 0")
        self.lbl_disabled.setToolTip(self._("Click to show disabled and muted hosts"))
        self.lbl_disabled.clicked.connect(lambda: self.toggle_summary_filter("disabled"))
        self.lbl_loss = QLabel("Loss: 0.0%")
        if has_fping():
            self.lbl_engine = QLabel(f"Engine: fping (batch {self.fping_batch_size})")
        else:
            self.lbl_engine = QLabel("Engine: ping")
        for w in (self.lbl_total, self.lbl_ok, self.lbl_warn, self.lbl_down,
                  self.lbl_disabled, self.lbl_loss):
            sl.addWidget(w)
            sl.addWidget(QLabel("|"))
        sl.addWidget(self.lbl_engine)
        sl.addStretch()
        self._apply_summary_styles()

        main_panel = QHBoxLayout()

        left = QWidget()
        self.left_panel = left
        ll = QVBoxLayout()
        left.setLayout(ll)
        self.hosts_caption = QLabel(self._("Monitored Hosts:"))
        ll.addWidget(self.hosts_caption)

        search_row = QWidget()
        sr = QHBoxLayout()
        sr.setContentsMargins(0, 0, 0, 0)
        search_row.setLayout(sr)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText(self._("Search host..."))
        self.search_input.setClearButtonEnabled(True)
        self.search_input.textChanged.connect(self.on_search_changed)
        sr.addWidget(self.search_input, 1)

        self.expand_all_btn = QPushButton("＋")
        self.expand_all_btn.setToolTip(self._("Expand all groups"))
        self.expand_all_btn.setFixedWidth(30)
        self.expand_all_btn.clicked.connect(self.expand_all_groups)
        sr.addWidget(self.expand_all_btn)

        self.collapse_all_btn = QPushButton("−")
        self.collapse_all_btn.setToolTip(self._("Collapse all groups"))
        self.collapse_all_btn.setFixedWidth(30)
        self.collapse_all_btn.clicked.connect(self.collapse_all_groups)
        sr.addWidget(self.collapse_all_btn)

        ll.addWidget(search_row)
        ll.addWidget(self.host_list)

        right = QWidget()
        rl = QVBoxLayout()
        right.setLayout(rl)
        rl.addWidget(self.time_scale)
        rl.addWidget(self.scroll_area)
        scroll_content = QWidget()
        self.right_panel_layout = QVBoxLayout()
        scroll_content.setLayout(self.right_panel_layout)
        self.scroll_area.setWidget(scroll_content)

        main_panel.addWidget(left, 0)
        main_panel.addWidget(right, 1)

        layout.addWidget(control_panel)
        layout.addWidget(summary_panel)
        layout.addLayout(main_panel)

    # ---------- Search ----------

    def on_search_changed(self, text):
        self.search_text = text.strip().lower()
        self.apply_filter()
        if self.search_text:
            self._select_first_visible_host()
        else:
            self._restore_focus_after_search_clear()

    def _on_host_selection_changed(self):
        sel = [i for i in self.host_list.selectedItems() if i.parent() is not None]
        if sel:
            host = sel[0].data(0, Qt.ItemDataRole.UserRole)
            if host:
                self._focused_host = host

    def _restore_focus_after_search_clear(self):
        if not self._focused_host or self._focused_host not in self.host_widgets:
            return
        host = self._focused_host
        w = self.host_widgets[host]
        self._select_host_in_tree(host)
        if w.isVisible():
            QTimer.singleShot(0, lambda: self.scroll_area.ensureWidgetVisible(w))

    def _select_first_visible_host(self):
        selected = self.host_list.selectedItems()
        still_visible = [
            it for it in selected
            if it.parent() is not None and not it.isHidden()
        ]
        if still_visible:
            return
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            if ci.isHidden():
                continue
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.isHidden():
                    continue
                ci.setExpanded(True)
                self.host_list.clearSelection()
                hi.setSelected(True)
                self.host_list.setCurrentItem(hi)
                self.host_list.scrollToItem(hi)
                host = hi.data(0, Qt.ItemDataRole.UserRole)
                if host:
                    self._focused_host = host
                return

    def _select_host_in_tree(self, host):
        if not host:
            return
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.data(0, Qt.ItemDataRole.UserRole) == host:
                    ci.setExpanded(True)
                    self.host_list.clearSelection()
                    hi.setSelected(True)
                    self.host_list.setCurrentItem(hi)
                    self.host_list.scrollToItem(hi)
                    self._focused_host = host
                    return

    def expand_all_groups(self):
        for i in range(self.host_list.topLevelItemCount()):
            self.host_list.topLevelItem(i).setExpanded(True)

    def collapse_all_groups(self):
        for i in range(self.host_list.topLevelItemCount()):
            self.host_list.topLevelItem(i).setExpanded(False)

    def _host_should_show(self, widget, host):
        if self.search_text and self.search_text not in host.lower():
            return False
        if self.filter_mode == "disabled":
            return widget.disabled or widget.muted
        if widget.disabled:
            return self.filter_mode == "all"
        if self.filter_mode == "failed":
            return widget.consecutive_failures >= self.alerts_after_failures
        if self.filter_mode == "warn":
            return 1 <= widget.consecutive_failures < self.alerts_after_failures
        return True

    # ---------- Summary ----------

    def update_status_panel(self):
        total = len(self.host_widgets)
        ok = warn = down = inactive = 0
        tot_ok = tot_fail = 0
        for w in self.host_widgets.values():
            if w.disabled or w.muted:
                inactive += 1
                if w.disabled:
                    continue
            cf = w.consecutive_failures
            if cf >= self.alerts_after_failures:
                down += 1
            elif cf >= 1:
                warn += 1
            else:
                ok += 1
            tot_ok += w.session_success_count
            tot_fail += w.session_failure_count
        checks = tot_ok + tot_fail
        loss = (tot_fail / checks * 100) if checks > 0 else 0.0
        self.lbl_total.setText(f"Total: {total}")
        self.lbl_ok.setText(f"OK: {ok}")
        self.lbl_warn.setText(f"Warn: {warn}")
        self.lbl_down.setText(f"Down: {down}")
        self.lbl_disabled.setText(f"Disabled: {inactive}")
        self.lbl_loss.setText(f"Loss: {loss:.1f}%")
        self._apply_summary_styles()

    # ---------- Settings ----------

    def show_settings_dialog(self):
        dialog = QDialog(self)
        dialog.setWindowTitle(self._("Settings"))
        dialog.resize(520, 620)
        layout = QVBoxLayout(dialog)
        tabs = QTabWidget()

        general = QWidget()
        gl = QFormLayout(general)

        # --- Appearance ---
        appearance_combo = QComboBox()
        appearance_combo.addItem(self._("Auto (follow system)"), "auto")
        appearance_combo.addItem(self._("Light"), "light")
        appearance_combo.addItem(self._("Dark"), "dark")
        idx = appearance_combo.findData(self.appearance)
        if idx >= 0:
            appearance_combo.setCurrentIndex(idx)
        gl.addRow(self._("Appearance:"), appearance_combo)

        retention_spin = QSpinBox(); retention_spin.setRange(1, 365 * 24)
        if self.retention_hours % 24 == 0 and self.retention_hours >= 24:
            retention_spin.setValue(self.retention_hours // 24); unit_init = 1
        else:
            retention_spin.setValue(self.retention_hours); unit_init = 0
        retention_unit = QComboBox(); retention_unit.addItems([self._("hours"), self._("days")])
        retention_unit.setCurrentIndex(unit_init)
        row = QWidget(); rl = QHBoxLayout(); rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(retention_spin, 1); rl.addWidget(retention_unit, 1); row.setLayout(rl)
        gl.addRow(self._("Keep history for:"), row)

        esc_check = QCheckBox(self._("Minimize to tray on Escape"))
        esc_check.setChecked(self.minimize_on_escape)
        gl.addRow("", esc_check)

        timeout_spin = QSpinBox()
        timeout_spin.setRange(0, 60000)
        timeout_spin.setSingleStep(100)
        timeout_spin.setSuffix(" ms")
        timeout_spin.setValue(self.ping_timeout_ms)
        timeout_spin.setSpecialValueText(self._("Auto (follows interval)"))
        gl.addRow(self._("Response timeout:"), timeout_spin)

        batch_spin = QSpinBox()
        batch_spin.setRange(1, 100)
        batch_spin.setValue(self.fping_batch_size)
        batch_spin.setEnabled(has_fping())
        gl.addRow(self._("fping batch size (hosts per call):"), batch_spin)
        if not has_fping():
            fping_hint = QLabel(self._("fping not found — batch size has no effect."))
            fping_hint.setStyleSheet(f"color: {palette().text_dim.name()}; font-size: 10px;")
            gl.addRow("", fping_hint)

        latency_check = QCheckBox(self._("Show latency scale on graphs"))
        latency_check.setChecked(self.graph_show_latency)
        gl.addRow("", latency_check)

        height_combo = QComboBox()
        height_combo.addItem(self._("Compact (50px)"), "compact")
        height_combo.addItem(self._("Normal (80px)"), "normal")
        height_combo.addItem(self._("Expanded (200px)"), "expanded")
        idx = height_combo.findData(self.graph_height_mode)
        if idx >= 0:
            height_combo.setCurrentIndex(idx)
        gl.addRow(self._("Graph height:"), height_combo)

        tabs.addTab(general, self._("General"))

        alerts = QWidget()
        al = QFormLayout(alerts)
        alert_after = QSpinBox(); alert_after.setRange(1, 100)
        alert_after.setValue(self.alerts_after_failures)
        al.addRow(self._("Alert after N consecutive failures:"), alert_after)
        reminder = QSpinBox(); reminder.setRange(1, 1440)
        reminder.setValue(self.alert_reminder_minutes)
        reminder.setSuffix(" min")
        al.addRow(self._("Remind every:"), reminder)
        recovery_check = QCheckBox(self._("Notify when host recovers"))
        recovery_check.setChecked(self.notify_on_recovery)
        al.addRow("", recovery_check)
        tabs.addTab(alerts, self._("Alerts"))

        storage = QWidget()
        st = QFormLayout(storage)
        cleanup_check = QCheckBox(self._("Auto-cleanup old history files"))
        cleanup_check.setChecked(self.cleanup_enabled)
        st.addRow("", cleanup_check)
        cleanup_days = QSpinBox(); cleanup_days.setRange(1, 3650)
        cleanup_days.setValue(self.cleanup_days)
        cleanup_days.setSuffix(" days")
        st.addRow(self._("Delete archives older than:"), cleanup_days)
        info = QLabel(self._("Files are deleted from ~/.config/QPing/history/. This cannot be undone."))
        info.setWordWrap(True)
        info.setStyleSheet(f"color: {palette().text_dim.name()}; font-size: 10px;")
        st.addRow(info)
        tabs.addTab(storage, self._("Storage"))

        hooks = QWidget()
        hl = QFormLayout(hooks)
        hooks_check = QCheckBox(self._("Enable event hooks"))
        hooks_check.setChecked(self.hooks_enabled)
        hl.addRow("", hooks_check)
        hooks_path_lbl = QLabel(self.hooks_dir)
        hooks_path_lbl.setWordWrap(True)
        hooks_path_lbl.setStyleSheet(f"color: {palette().text_dim.name()};")
        choose_btn = QPushButton(self._("Choose directory..."))
        def choose_hooks_dir():
            d = QFileDialog.getExistingDirectory(self, self._("Hooks directory"), self.hooks_dir)
            if d:
                hooks_path_lbl.setText(d)
        choose_btn.clicked.connect(choose_hooks_dir)
        hl.addRow(self._("Hooks directory:"), hooks_path_lbl)
        hl.addRow("", choose_btn)
        hint = QLabel(self._(
            "Scripts: on_host_down.sh and on_host_up.sh (must be executable).\n"
            "Environment variables: QPING_HOST, QPING_STATUS (down/up), QPING_FAILURES, QPING_TIMESTAMP."
        ))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {palette().text_dim.name()}; font-size: 10px;")
        hl.addRow(hint)
        tabs.addTab(hooks, self._("Hooks"))

        layout.addWidget(tabs)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)

        if dialog.exec() == QDialog.DialogCode.Accepted:
            # --- Appearance ---
            new_appearance = appearance_combo.currentData()
            if new_appearance != self.appearance:
                self.apply_appearance(new_appearance)

            # --- Latency scale ---
            new_latency = latency_check.isChecked()
            if new_latency != self.graph_show_latency:
                self.graph_show_latency = new_latency
                self.settings.setValue("graph_show_latency", new_latency)
                self.time_scale.set_left_gutter(
                    PingGraphWidget.LEFT_GUTTER if new_latency else 0
                )
                for w in self.host_widgets.values():
                    w.graph_widget.set_show_latency(new_latency)

            # --- Graph height mode ---
            new_height = height_combo.currentData()
            if new_height != self.graph_height_mode:
                self.apply_graph_height(new_height)

            value = retention_spin.value()
            new_hours = value * 24 if retention_unit.currentIndex() == 1 else value
            new_hours = max(1, new_hours)
            self.retention_hours = new_hours
            self.settings.setValue("retention_hours", new_hours)
            for w in self.host_widgets.values():
                w.retention_hours = new_hours
                w.prune_to_retention()

            self.minimize_on_escape = esc_check.isChecked()
            self.settings.setValue("minimize_on_escape", self.minimize_on_escape)

            self.ping_timeout_ms = max(0, timeout_spin.value())
            self.settings.setValue("ping_timeout_ms", self.ping_timeout_ms)
            self.ping_manager.set_ping_timeout(self.ping_timeout_ms)

            new_batch = batch_spin.value()
            self.fping_batch_size = max(1, new_batch)
            self.settings.setValue("fping_batch_size", self.fping_batch_size)
            if has_fping():
                self.lbl_engine.setText(f"Engine: fping (batch {self.fping_batch_size})")

            self.alerts_after_failures = alert_after.value()
            self.alert_reminder_minutes = reminder.value()
            self.notify_on_recovery = recovery_check.isChecked()
            self.settings.setValue("alerts_after_failures", self.alerts_after_failures)
            self.settings.setValue("alert_reminder_minutes", self.alert_reminder_minutes)
            self.settings.setValue("notify_on_recovery", self.notify_on_recovery)

            self.cleanup_enabled = cleanup_check.isChecked()
            self.cleanup_days = cleanup_days.value()
            self.settings.setValue("cleanup_enabled", self.cleanup_enabled)
            self.settings.setValue("cleanup_days", self.cleanup_days)

            self.hooks_enabled = hooks_check.isChecked()
            self.hooks_dir = hooks_path_lbl.text()
            os.makedirs(self.hooks_dir, exist_ok=True)
            self.settings.setValue("hooks_enabled", self.hooks_enabled)
            self.settings.setValue("hooks_dir", self.hooks_dir)

            self.update_all_graphs()
            self.update_status_panel()

    # ---------- Hooks ----------

    def fire_hook(self, event, host, failures=0):
        if not self.hooks_enabled:
            return
        script = os.path.join(self.hooks_dir, f"on_host_{event}.sh")
        if not os.path.isfile(script) or not os.access(script, os.X_OK):
            return
        env = {
            "QPING_HOST": host,
            "QPING_STATUS": event,
            "QPING_FAILURES": str(failures),
            "QPING_TIMESTAMP": datetime.now().isoformat(),
        }
        worker = HookWorker(script, env)
        self.hook_pool.start(worker)

    def _queue_notification(self, event, host, failures=0):
        """Push an event onto the queue. The aggregate is shown 2 seconds
        after the first event in the window (single-shot timer)."""
        self._notify_queue.append({
            "event": event,
            "host": host,
            "failures": failures,
        })
        if not self._notify_timer.isActive():
            self._notify_timer.start()

    def _flush_notifications(self):
        if not self._notify_queue:
            return
        queue = self._notify_queue
        self._notify_queue = []

        # Unique hosts, preserving order
        def _uniq(seq):
            seen = set()
            out = []
            for x in seq:
                if x not in seen:
                    seen.add(x)
                    out.append(x)
            return out

        down_hosts = _uniq([n["host"] for n in queue if n["event"] == "down"])
        up_hosts = _uniq([n["host"] for n in queue if n["event"] == "up"])

        if not self.notifications_enabled:
            return

        if not self.tray_icon.isVisible():
            self.tray_icon.setVisible(True)

        def _preview(lst, limit=5):
            if len(lst) <= limit:
                return ", ".join(lst)
            return ", ".join(lst[:limit]) + "…"

        if down_hosts:
            if len(down_hosts) == 1:
                title = self._("Host unavailable")
                text = self._("Host {} is not responding").format(down_hosts[0])
            else:
                title = self._("Hosts unavailable")
                text = self._("{} hosts are not responding:\n{}").format(
                    len(down_hosts), _preview(down_hosts))
            self.tray_icon.showMessage(
                title, text,
                QSystemTrayIcon.MessageIcon.Warning, 5000)

        if up_hosts:
            if len(up_hosts) == 1:
                title = self._("Host recovered")
                text = self._("Host {} is responding again").format(up_hosts[0])
            else:
                title = self._("Hosts recovered")
                text = self._("{} hosts are responding again:\n{}").format(
                    len(up_hosts), _preview(up_hosts))
            self.tray_icon.showMessage(
                title, text,
                QSystemTrayIcon.MessageIcon.Information, 5000)

    # ---------- Auto-cleanup ----------

    def run_auto_cleanup(self):
        if not self.cleanup_enabled:
            return
        cutoff_date = datetime.now() - timedelta(days=self.cleanup_days)
        removed = 0
        try:
            for host_dir_name in os.listdir(HISTORY_DIR):
                host_dir = os.path.join(HISTORY_DIR, host_dir_name)
                if not os.path.isdir(host_dir):
                    continue
                for fname in os.listdir(host_dir):
                    if not fname.endswith(".jsonl"):
                        continue
                    day_str = fname[:-6]
                    try:
                        d = datetime.strptime(day_str, "%Y-%m-%d")
                    except ValueError:
                        continue
                    if d < cutoff_date:
                        try:
                            os.remove(os.path.join(host_dir, fname))
                            removed += 1
                        except OSError as e:
                            print(f"[cleanup] {fname}: {e}")
        except Exception as e:
            print(f"[cleanup] {e}")
        if removed:
            print(f"[cleanup] Removed {removed} old history files")

    # ---------- Notifications / filter ----------

    def toggle_notifications(self):
        self.notifications_enabled = not self.notifications_enabled
        self.mute_button.setText(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self.settings.setValue("notifications_enabled", self.notifications_enabled)

    def toggle_filter(self):
        """Cycle through modes: all → failed → warn → disabled → all."""
        order = ["all", "failed", "warn", "disabled"]
        i = order.index(self.filter_mode) if self.filter_mode in order else 0
        self.filter_mode = order[(i + 1) % len(order)]
        self.settings.setValue("filter_mode", self.filter_mode)
        self._update_filter_button_text()
        self._apply_summary_styles()
        self.apply_filter()
        self.reorder_graphs()

    def _update_filter_button_text(self):
        labels = {
            "all": self._("Filter: All"),
            "failed": self._("Filter: Failed"),
            "warn": self._("Filter: Warn"),
            "disabled": self._("Filter: Disabled"),
        }
        if hasattr(self, "filter_button"):
            self.filter_button.setText(labels.get(self.filter_mode, labels["all"]))

    def toggle_summary_filter(self, mode):
        """Click on Warn / Down / Disabled toggles the filter. A second click
        on the active mode returns to 'all'."""
        if self.filter_mode == mode:
            self.filter_mode = "all"
        else:
            self.filter_mode = mode
        self.settings.setValue("filter_mode", self.filter_mode)
        self._update_filter_button_text()
        self._apply_summary_styles()
        self.apply_filter()
        self.reorder_graphs()

    def apply_filter(self):
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            visible = 0
            total = 0
            for j in range(ci.childCount()):
                hi = ci.child(j)
                host = hi.data(0, Qt.ItemDataRole.UserRole)
                w = self.host_widgets.get(host)
                if not w:
                    continue
                total += 1
                show = self._host_should_show(w, host)
                hi.setHidden(not show)
                w.setVisible(show)
                if show:
                    visible += 1
            cat_name = ci.data(0, Qt.ItemDataRole.UserRole)
            if self.filter_mode != "all" or self.search_text:
                ci.setText(0, f"[{cat_name}] ({visible}/{total})")
                ci.setHidden(visible == 0)
            else:
                ci.setText(0, f"[{cat_name}] ({total})")
                ci.setHidden(False)
        self.update_status_panel()

    # ---------- Help ----------

    def show_help(self):
        from help import build_help_html
        dlg = QDialog(self)
        dlg.setWindowTitle(self._("User Guide"))
        dlg.resize(700, 560)
        layout = QVBoxLayout()
        text_edit = QTextEdit()
        text_edit.setReadOnly(True)
        text_edit.setHtml(build_help_html(self._))
        layout.addWidget(text_edit)
        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        button_box.accepted.connect(dlg.accept)
        layout.addWidget(button_box)
        dlg.setLayout(layout)
        dlg.exec()

    def _read_changelog(self):
        """Return the changelog text.

        Priority:
          1. debian/changelog next to main.py — running from a source tree
             (e.g. cloned from GitHub).
          2. /usr/share/doc/qping/changelog.Debian.gz — Debian/PPA install.
          3. /usr/share/doc/qping/changelog.gz — upstream changelog
             shipped by the package.
        Returns a string, or None if nothing is found.
        """
        local_changelog = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "debian", "changelog"
        )
        candidates = [
            (local_changelog, False),
            ("/usr/share/doc/qping/changelog.Debian.gz", True),
            ("/usr/share/doc/qping/changelog.gz", True),
        ]
        for path, gz in candidates:
            if not os.path.isfile(path):
                continue
            try:
                if gz:
                    with gzip.open(path, "rt", encoding="utf-8", errors="replace") as f:
                        return f.read()
                else:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()
            except Exception as e:
                print(f"[about] Failed to read {path}: {e}")
        return None

    def show_about(self):
        """Display the About dialog: version, author, project link, changelog."""
        dlg = QDialog(self)
        dlg.setWindowTitle(self._("About QPing"))
        dlg.resize(640, 560)

        outer = QVBoxLayout(dlg)

        # --- Header: icon + name/version + author + link ---
        header_row = QHBoxLayout()
        icon_label = QLabel()
        icon_pix = self.windowIcon().pixmap(64, 64)
        icon_label.setPixmap(icon_pix)
        icon_label.setFixedSize(64, 64)
        header_row.addWidget(icon_label, 0, Qt.AlignmentFlag.AlignTop)

        header_text = QWidget()
        hl = QVBoxLayout(header_text)
        hl.setContentsMargins(8, 0, 0, 0)
        hl.setSpacing(2)

        name_lbl = QLabel(f"<h2 style='margin:0;'>QPing {APP_VERSION}</h2>")
        hl.addWidget(name_lbl)

        subtitle_lbl = QLabel(self._("Network host monitor with ICMP ping and TCP port checks."))
        subtitle_lbl.setWordWrap(True)
        hl.addWidget(subtitle_lbl)

        author_lbl = QLabel(self._("Author: {}").format("Sergei Parhomenko &lt;zersh@mail.ru&gt;"))
        author_lbl.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(author_lbl)

        link_lbl = QLabel(
            f'<a href="https://github.com/zersh01/QPing">'
            f'https://github.com/zersh01/QPing</a>'
        )
        link_lbl.setOpenExternalLinks(True)
        link_lbl.setTextFormat(Qt.TextFormat.RichText)
        hl.addWidget(link_lbl)

        license_lbl = QLabel(self._("License: MIT"))
        hl.addWidget(license_lbl)

        hl.addStretch()
        header_row.addWidget(header_text, 1)
        outer.addLayout(header_row)

        # --- Changelog ---
        changelog_caption = QLabel(self._("Changelog:"))
        changelog_caption.setStyleSheet("font-weight: bold; margin-top: 6px;")
        outer.addWidget(changelog_caption)

        changelog_view = QTextEdit()
        changelog_view.setReadOnly(True)
        changelog_view.setFont(QFont("Monospace", 9))
        text = self._read_changelog()
        if text:
            changelog_view.setPlainText(text)
        else:
            changelog_view.setPlainText(
                self._("Changelog is not available.\n\n"
                       "When installed from a .deb package, the file is located at:\n"
                       "  /usr/share/doc/qping/changelog.Debian.gz")
            )
        outer.addWidget(changelog_view, 1)

        # --- Buttons ---
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(dlg.reject)
        buttons.accepted.connect(dlg.accept)
        outer.addWidget(buttons)

        dlg.exec()

    # ---------- Localization ----------

    def change_language(self, lang):
        self.language = lang
        self._ = setup_localization(lang)
        self.settings.setValue("language", lang)
        if hasattr(self, "_lang_actions"):
            for code, action in self._lang_actions.items():
                action.setChecked(code == lang)
        self.retranslate_ui()

    def retranslate_ui(self):
        if not hasattr(self, 'host_list') or self.host_list is None:
            return
        self.setWindowTitle(f"{self._('QPing Monitor')} {APP_VERSION}")
        self.host_input.setPlaceholderText(self._("Enter IP/domain"))
        self.search_input.setPlaceholderText(self._("Search host..."))
        self.add_button.setText(self._("Add Host"))
        self.import_button.setText(self._("Import from File"))
        self.interval_label.setText(self._("Interval: {}ms").format(self.interval_slider.value()))
        self.mute_button.setText(
            self._("Notifications: On") if self.notifications_enabled
            else self._("Notifications: Off")
        )
        self._update_filter_button_text()
        if hasattr(self, 'interval_caption'):
            self.interval_caption.setText(self._("Interval:"))
        if hasattr(self, 'hosts_caption'):
            self.hosts_caption.setText(self._("Monitored Hosts:"))

        self.menu_app.setTitle(self._("Application"))
        self.action_settings.setText(self._("Settings..."))
        self.action_export.setText(self._("Export Hosts..."))
        self.action_import.setText(self._("Import Hosts..."))
        self.action_close.setText(self._("Close"))
        self.action_quit.setText(self._("Quit"))

        self.menu_help.setTitle(self._("Help"))
        self.action_help.setText(self._("User Guide"))
        self.action_about.setText(self._("About"))

        self.menu_lang.setTitle(self._("Language"))
        # Language names are not translated — they are native and only change
        # when the language itself changes. But update the checkmark in case
        # the language was changed programmatically.
        if hasattr(self, "_lang_actions"):
            for code, action in self._lang_actions.items():
                action.setChecked(code == self.language)

        if hasattr(self, 'tray_action_restore'):
            self.tray_action_restore.setText(self._("Restore"))
            self.tray_action_quit.setText(self._("Quit"))

        self.update_host_list_display()
        self.update_all_graphs()

    # ---------- Context menu ----------

    def show_host_context_menu(self, position):
        """From the tree: position is relative to host_list."""
        self._show_host_context_menu_at(self.host_list.mapToGlobal(position))

    def _on_host_context_menu_from_graph(self, host, global_pos):
        """From a graph: select the corresponding host first, then show the menu."""
        if host in self.host_widgets:
            self._select_host_in_tree(host)
        self._show_host_context_menu_at(global_pos)

    def _show_host_context_menu_at(self, global_pos):
        sel = self.host_list.selectedItems()
        menu = QMenu()
        pos_in_tree = self.host_list.mapFromGlobal(global_pos)
        clicked = self.host_list.itemAt(pos_in_tree)

        if clicked and clicked.parent() is None:
            cat = clicked.data(0, Qt.ItemDataRole.UserRole)
            act = QAction(self._("Delete Category '{}'").format(cat), self)
            act.triggered.connect(lambda: self.delete_category(cat))
            act.setEnabled(cat != "Default")
            menu.addAction(act)
            menu.exec(global_pos)
            return

        hosts = [i.data(0, Qt.ItemDataRole.UserRole) for i in sel
                 if i.parent() is not None and i.data(0, Qt.ItemDataRole.UserRole)]

        if hosts:
            edit_action = QAction(self._("Edit (F2)"), self)
            edit_action.triggered.connect(lambda: self.edit_host(hosts[0]))
            edit_action.setEnabled(len(hosts) == 1)

            delete_action = QAction(self._("Delete (Del)"), self)
            delete_action.triggered.connect(lambda: self.delete_hosts(hosts))

            ping_now_action = QAction(self._("Ping now"), self)
            ping_now_action.triggered.connect(lambda: self.ping_now(hosts))

            any_disabled = all(self.host_widgets[h].disabled for h in hosts if h in self.host_widgets)
            disable_label = self._("Enable monitoring") if any_disabled else self._("Disable monitoring")
            disable_action = QAction(disable_label, self)
            disable_action.triggered.connect(lambda: self.toggle_disabled(hosts))

            any_unmuted = not all(
                self.host_widgets[h].muted
                for h in hosts if h in self.host_widgets
            )
            mute_label = self._("Mute notifications") if any_unmuted else self._("Unmute notifications")
            mute_action = QAction(mute_label, self)
            mute_action.triggered.connect(lambda: self.toggle_muted(hosts))

            check_type_menu = QMenu(self._("Check Type"), self)
            icmp_a = QAction(self._("ICMP Ping"), self)
            tcp_a = QAction(self._("TCP Port"), self)
            icmp_a.triggered.connect(lambda: self.set_check_type(hosts, 'icmp'))
            tcp_a.triggered.connect(lambda: self.set_check_type(hosts, 'tcp'))
            check_type_menu.addAction(icmp_a); check_type_menu.addAction(tcp_a)
            check_type_menu.setEnabled(len(hosts) == 1)

            height_menu = QMenu(self._("Graph height"), self)
            for label, mode in ((self._("Compact"), "compact"),
                                (self._("Normal"), "normal"),
                                (self._("Expanded"), "expanded")):
                a = QAction(label, self)
                a.setCheckable(True)
                a.setChecked(self.graph_height_mode == mode)
                a.triggered.connect(lambda _checked=False, m=mode: self.apply_graph_height(m))
                height_menu.addAction(a)

            cat_action = QAction(self._("Set Category"), self)
            cat_action.triggered.connect(lambda: self.set_host_category(hosts))

            clear_action = QAction(self._("Clear History"), self)
            clear_action.triggered.connect(lambda: self.clear_host_history(hosts))

            load_action = QAction(self._("Load Full History"), self)
            load_action.triggered.connect(lambda: self.load_full_history(hosts))

            menu.addAction(edit_action)
            menu.addAction(delete_action)
            menu.addAction(ping_now_action)
            menu.addAction(disable_action)
            menu.addAction(mute_action)
            menu.addSeparator()
            menu.addMenu(check_type_menu)
            menu.addMenu(height_menu)
            menu.addAction(cat_action)
            menu.addSeparator()
            menu.addAction(clear_action)
            menu.addAction(load_action)
        else:
            imp = QAction(self._("Import from File"), self)
            imp.triggered.connect(self.import_hosts_from_file)
            menu.addAction(imp)

        menu.exec(global_pos)

    # ---------- Ping now / Disable / Mute ----------

    def ping_now(self, hosts):
        for host in reversed(hosts):
            if host in self.icmp_queue:
                self.icmp_queue.remove(host)
                self.icmp_queue.insert(0, host)
            elif host in self.tcp_queue:
                self.tcp_queue.remove(host)
                self.tcp_queue.insert(0, host)
        self.icmp_idx = 0
        self.tcp_idx = 0
        self.ping_tick()

    def toggle_disabled(self, hosts):
        for h in hosts:
            if h in self.host_widgets:
                self.host_widgets[h].set_disabled(not self.host_widgets[h].disabled)
        self.update_host_list_display()
        self.update_host_queue()
        self.reorder_graphs()
        self.apply_filter()
        self.save_data()

    def toggle_muted(self, hosts):
        for h in hosts:
            if h in self.host_widgets:
                w = self.host_widgets[h]
                w.set_muted(not w.muted)
        self.update_host_list_display()
        self.save_data()
        self.apply_filter()
        self.update_app_icon()

    # ---------- Categories ----------

    def delete_category(self, category_name):
        if category_name == "Default":
            return
        hosts_in_cat = [h for h, w in self.host_widgets.items() if w.category == category_name]
        if hosts_in_cat:
            mb = QMessageBox(self)
            mb.setWindowTitle(self._("Delete Category"))
            mb.setText(self._("Category '{}' contains {} hosts. What would you like to do?").format(category_name, len(hosts_in_cat)))
            move_btn = mb.addButton(self._("Move hosts to Default"), QMessageBox.ButtonRole.ActionRole)
            delete_btn = mb.addButton(self._("Delete all hosts"), QMessageBox.ButtonRole.DestructiveRole)
            mb.addButton(QMessageBox.StandardButton.Cancel)
            mb.exec()
            if mb.clickedButton() == move_btn:
                for h in hosts_in_cat:
                    self.host_widgets[h].category = "Default"
            elif mb.clickedButton() == delete_btn:
                for h in hosts_in_cat:
                    self.host_widgets[h].deleteLater()
                    del self.host_widgets[h]
            else:
                return
        else:
            r = QMessageBox.question(self, self._("Delete Category"),
                                     self._("Delete empty category '{}'?").format(category_name),
                                     QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        if category_name in self.categories_list:
            self.categories_list.remove(category_name)
        self.update_host_list_display()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()
        self.update_host_queue()

    def set_host_category(self, hosts):
        class CategoryDialog(QDialog):
            def __init__(self, parent, existing):
                super().__init__(parent)
                self.setWindowTitle(parent._("Set Category"))
                lay = QVBoxLayout(self)
                self.combo = QComboBox()
                self.combo.addItem("Default")
                self.combo.addItems(sorted([c for c in existing if c != "Default"]))
                self.combo.addItem(parent._("New Category"))
                lay.addWidget(self.combo)
                self.text_input = QLineEdit()
                self.text_input.setPlaceholderText(parent._("Enter new category name"))
                self.text_input.setVisible(False)
                lay.addWidget(self.text_input)
                self.combo.currentIndexChanged.connect(self.toggle)
                bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
                bb.accepted.connect(self.accept); bb.rejected.connect(self.reject)
                lay.addWidget(bb)
            def toggle(self, idx):
                self.text_input.setVisible(self.combo.currentText() == self.parent()._("New Category"))
            def get_category(self):
                if self.combo.currentText() == self.parent()._("New Category"):
                    return self.text_input.text().strip()
                return self.combo.currentText()
        d = CategoryDialog(self, self.categories_list)
        if d.exec() == QDialog.DialogCode.Accepted:
            cat = d.get_category()
            if cat:
                if cat not in self.categories_list:
                    self.categories_list.append(cat)
                for h in hosts:
                    if h in self.host_widgets:
                        self.host_widgets[h].category = cat
                self.update_host_list_display()
                self.reorder_graphs()
                self.save_data()
                self.apply_filter()

    # ---------- Check type ----------

    def set_check_type(self, hosts, check_type):
        if not hosts:
            return
        host = hosts[0] if isinstance(hosts, list) else hosts
        if check_type == 'tcp':
            port, ok = QInputDialog.getInt(self, self._("TCP Port"),
                                           self._("Enter port number (1-65535):"),
                                           value=80, min=1, max=65535)
            if not ok:
                return
            self.host_check_types[host] = {'type': 'tcp', 'port': port}
            if host in self.host_widgets:
                self.host_widgets[host].set_check_type('tcp', port)
        else:
            self.host_check_types[host] = {'type': 'icmp', 'port': None}
            if host in self.host_widgets:
                self.host_widgets[host].set_check_type('icmp', None)
        self.update_host_item_text(host)
        self.save_data()
        self.apply_filter()
        self.update_host_queue()

    def get_host_check_tag(self, host):
        info = self.host_check_types.get(host, {'type': 'icmp', 'port': None})
        if info.get('type') == 'tcp' and info.get('port') is not None:
            return f"[p:{info['port']}]"
        return "[i]"

    def update_host_item_text(self, host):
        if host not in self.host_widgets:
            return
        w = self.host_widgets[host]
        muted_tag = " [muted]" if w.muted else ""
        text = f"{host} {self.get_host_check_tag(host)}{muted_tag}"
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                c = ci.child(j)
                if c.data(0, Qt.ItemDataRole.UserRole) == host:
                    c.setText(0, text)
                    return

    # ---------- Deletion ----------

    def delete_hosts(self, hosts):
        r = QMessageBox.question(self, self._("Delete"),
                                 self._("Delete {} hosts?").format(len(hosts)),
                                 QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r == QMessageBox.StandardButton.Yes:
            for h in hosts:
                if h in self.host_widgets:
                    self.host_widgets[h].deleteLater()
                    del self.host_widgets[h]
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()
            if not self.host_widgets:
                self.ping_timer.stop()

    # ---------- Clear / load history ----------

    def clear_host_history(self, hosts):
        if not hosts:
            return
        r = QMessageBox.question(
            self, self._("Clear History"),
            self._("Delete all history for {} host(s)?\n\n"
                   "This erases in-memory records and deletes all saved files "
                   "in ~/.config/QPing/history/ for the selected host(s).").format(len(hosts)),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        for h in hosts:
            if h not in self.host_widgets:
                continue
            w = self.host_widgets[h]
            w.ping_history.clear()
            w.loaded_days.clear()
            w.session_success_count = 0
            w.session_failure_count = 0
            w.consecutive_failures = 0
            w.last_notified = None
            w.last_saved_time = None
            w.was_down = False
            w.graph_widget.update_history(w.ping_history, 0, 0, self.app_start_time)
            hd = self._host_dir(h)
            if os.path.isdir(hd):
                try:
                    shutil.rmtree(hd)
                except Exception as e:
                    print(f"Failed to remove {hd}: {e}")
        self.apply_filter()
        self.reorder_graphs()

    def load_full_history(self, hosts):
        if not hosts:
            return
        to_load = {}
        cutoff_date = (datetime.now() - timedelta(hours=self.retention_hours)).date()
        for h in hosts:
            if h not in self.host_widgets:
                continue
            w = self.host_widgets[h]
            host_dir = self._host_dir(h)
            all_days = set(list_history_days(host_dir))
            all_days = {
                d for d in all_days
                if datetime.strptime(d, "%Y-%m-%d").date() >= cutoff_date
            }
            missing = all_days - w.loaded_days
            if missing:
                to_load[h] = sorted(missing)

        if to_load:
            self._queue_day_load(to_load)
            QMessageBox.information(
                self, self._("Load Full History"),
                self._("Loading history for {} host(s) in background.").format(len(to_load)))
        else:
            QMessageBox.information(
                self, self._("Load Full History"),
                self._("No additional history to load."))

    # ---------- Per-day history on-demand loading ----------

    def on_zoom_changed(self):
        if not self.host_widgets:
            return
        if self.time_scale.zoom_periods:
            visible_start, visible_end = self.time_scale.zoom_periods[-1]
        else:
            visible_start = self.time_scale.start_time
            visible_end = self.time_scale.end_time
        if visible_start is None or visible_end is None:
            return

        retention_cutoff = datetime.now() - timedelta(hours=self.retention_hours)
        if visible_start < retention_cutoff:
            visible_start = retention_cutoff

        days_needed = _days_between(visible_start, visible_end)

        to_load = {}
        for host, w in self.host_widgets.items():
            missing = days_needed - w.loaded_days
            if missing:
                to_load[host] = sorted(missing)

        if to_load:
            self._queue_day_load(to_load)

    def _queue_day_load(self, to_load):
        for host, days in to_load.items():
            self._pending_days.setdefault(host, set()).update(days)
        if self._history_loading_in_progress:
            return
        self._start_next_day_load()

    def _start_next_day_load(self):
        if not self._pending_days:
            return
        self._history_loading_in_progress = True
        batch = {h: sorted(d) for h, d in self._pending_days.items()}
        self._pending_days = {}
        host_dirs = {host: self._host_dir(host) for host in batch}
        worker = DayLoadWorker(host_dirs, batch)
        worker.signals.finished.connect(self._on_days_loaded)
        self.thread_pool.start(worker)

    @pyqtSlot(dict)
    def _on_days_loaded(self, result):
        self._history_loading_in_progress = False

        loaded_total = 0
        for host, data in result.items():
            if host not in self.host_widgets:
                continue
            w = self.host_widgets[host]

            w.loaded_days.update(data['days_loaded'])

            merged = w.ping_history + data['records']
            merged.sort(key=lambda x: x[0])
            deduped = []
            last_t = None
            for rec in merged:
                if last_t is not None and rec[0] == last_t:
                    continue
                deduped.append(rec)
                last_t = rec[0]
            w.ping_history = deduped

            file_latest = data.get('latest_time')
            if file_latest is not None and (
                w.last_saved_time is None or file_latest > w.last_saved_time
            ):
                w.last_saved_time = file_latest

            failures = 0
            for _, s, _ in reversed(deduped):
                if not s:
                    failures += 1
                else:
                    break
            w.consecutive_failures = failures

            w.graph_widget.update_history(
                w.ping_history, w.session_success_count,
                w.session_failure_count, self.app_start_time)
            loaded_total += len(data['records'])

        if loaded_total:
            print(f"[history] Loaded {loaded_total} records for {len(result)} host(s)")
        self.update_all_graphs()
        self.apply_filter()

        if self._pending_days:
            self._start_next_day_load()

    # ---------- Host list ----------

    def sorted_categories(self):
        others = sorted(c for c in self.categories_list if c != "Default")
        return ["Default"] + others

    def update_host_list_display(self):
        self.host_list.clear()
        p = palette()
        for category in self.sorted_categories():
            ci = QTreeWidgetItem(self.host_list)
            ci.setText(0, f"[{category}] (0)")
            ci.setData(0, Qt.ItemDataRole.UserRole, category)
            ci.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsDropEnabled)
            ci.setBackground(0, p.category_bg)
            ci.setExpanded(True)
            self.host_list.addTopLevelItem(ci)
        for host, w in self.host_widgets.items():
            if w.category not in self.categories_list:
                w.category = "Default"
            for i in range(self.host_list.topLevelItemCount()):
                ci = self.host_list.topLevelItem(i)
                if ci.data(0, Qt.ItemDataRole.UserRole) == w.category:
                    hi = QTreeWidgetItem(ci)
                    muted_tag = " [muted]" if w.muted else ""
                    hi.setText(0, f"{host} {self.get_host_check_tag(host)}{muted_tag}")
                    hi.setData(0, Qt.ItemDataRole.UserRole, host)
                    hi.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable |
                                Qt.ItemFlag.ItemIsDragEnabled)
                    hi.setForeground(0, self._host_color(w))
                    hi.setBackground(0, p.clear_bg)
                    ci.addChild(hi)
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            if self.filter_mode != "all" or self.search_text:
                vh = sum(1 for j in range(ci.childCount()) if not ci.child(j).isHidden())
                ci.setText(0, f"[{ci.data(0, Qt.ItemDataRole.UserRole)}] ({vh}/{ci.childCount()})")
            else:
                ci.setText(0, f"[{ci.data(0, Qt.ItemDataRole.UserRole)}] ({ci.childCount()})")
        self._update_tree_width()

    # ---------- Import ----------

    def import_hosts_from_file(self):
        file_name, _ = QFileDialog.getOpenFileName(
            self, self._("Import hosts"), "",
            self._("Supported (*.ini *.yml *.yaml *.txt *.qping.json hosts);;"
                   "Ansible INI (*.ini);;Ansible YAML (*.yml *.yaml);;"
                   "Hosts file (hosts);;Text list (*.txt);;"
                   "QPing backup (*.qping.json);;All files (*)"))
        if not file_name:
            return
        try:
            with open(file_name, 'r', encoding='utf-8') as f:
                content = f.read()
        except Exception as e:
            QMessageBox.critical(self, self._("Import error"), str(e))
            return

        fmt = detect_import_format(file_name, content)
        print(f"[import] file={file_name} format={fmt}")

        if fmt == 'backup':
            self._restore_backup(content)
            return

        if fmt == 'ansible_ini':
            groups = parse_ansible_ini(content)
        elif fmt == 'ansible_yaml':
            groups = parse_ansible_yaml(content)
            if groups is None:
                QMessageBox.warning(self, self._("Import"),
                    self._("YAML parsing requires PyYAML. Install with: pip install pyyaml"))
                return
        elif fmt == 'hosts':
            groups = parse_hosts_file(content)
        else:
            groups = parse_plain_list(content)

        if not groups:
            QMessageBox.warning(self, self._("Import"), self._("No hosts found."))
            return

        self._add_hosts_from_groups(groups)

    def _add_hosts_from_groups(self, groups):
        added = 0
        for group, hosts_list in groups.items():
            cat = group if group else "Default"
            if cat not in self.categories_list:
                self.categories_list.append(cat)
            for h in hosts_list:
                h = h.strip()
                if not h or h in self.host_widgets:
                    continue
                w = self._make_host_widget(h, cat)
                self.host_widgets[h] = w
                self._load_single_host_history(h, w)
                added += 1

        if added > 0:
            self.update_host_list_display()
            self.reorder_graphs()
            self.save_data()
            self.apply_filter()
            self.update_host_queue()
            if not self.ping_timer.isActive():
                self.start_pinging()
            QMessageBox.information(self, self._("Import completed"),
                                    self._("Successfully added {} hosts.").format(added))
        else:
            QMessageBox.warning(self, self._("Import"), self._("No new hosts added."))

    def _restore_backup(self, content):
        data = parse_backup(content)
        if data is None:
            QMessageBox.warning(self, self._("Restore"),
                                self._("Invalid QPing backup file."))
            return

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle(self._("Restore from backup"))
        msg_box.setText(self._("Backup contains {} host(s).\n\n"
                               "What would you like to do?").format(len(data)))
        replace_btn = msg_box.addButton(self._("Replace current list"),
                                        QMessageBox.ButtonRole.DestructiveRole)
        merge_btn = msg_box.addButton(self._("Merge with current"),
                                      QMessageBox.ButtonRole.ActionRole)
        cancel_btn = msg_box.addButton(QMessageBox.StandardButton.Cancel)
        msg_box.exec()

        if msg_box.clickedButton() == cancel_btn:
            return

        if msg_box.clickedButton() == replace_btn:
            for h in list(self.host_widgets.keys()):
                self.host_widgets[h].deleteLater()
                del self.host_widgets[h]
            self.host_check_types.clear()
            self.categories_list = ["Default"]

        added = 0
        for host, info in data.items():
            cat = info['category']
            if cat not in self.categories_list:
                self.categories_list.append(cat)

            if host not in self.host_widgets:
                w = self._make_host_widget(host, cat)
                self.host_widgets[host] = w
                self._load_single_host_history(host, w)
            else:
                w = self.host_widgets[host]
                w.category = cat

            ct = info.get('check_type', 'icmp')
            port = info.get('port')
            self.host_check_types[host] = {'type': ct, 'port': port}
            w.set_check_type(ct, port)
            w.set_disabled(info.get('disabled', False))
            w.set_muted(info.get('muted', False))
            added += 1

        self.update_host_list_display()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()
        self.update_host_queue()
        if self.host_widgets and not self.ping_timer.isActive():
            self.start_pinging()
        QMessageBox.information(self, self._("Restore completed"),
                                self._("Restored {} hosts.").format(added))

    def export_hosts_to_file(self):
        file_name, _ = QFileDialog.getSaveFileName(
            self, self._("Export hosts"),
            os.path.join(os.path.expanduser("~"), "qping_backup.qping.json"),
            self._("QPing backup (*.qping.json);;JSON (*.json);;All files (*)"))
        if not file_name:
            return
        if not (file_name.endswith('.qping.json') or file_name.endswith('.json')):
            file_name += '.qping.json'

        hosts_data = []

        def traverse(pi):
            for i in range(pi.childCount()):
                c = pi.child(i)
                h = c.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    w = self.host_widgets[h]
                    info = self.host_check_types.get(h, {'type': 'icmp', 'port': None})
                    hosts_data.append({
                        'host': h,
                        'category': w.category,
                        'check_type': info.get('type', 'icmp'),
                        'port': info.get('port'),
                        'disabled': bool(w.disabled),
                        'muted': bool(w.muted),
                    })

        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))

        backup = build_backup(hosts_data)
        try:
            with open(file_name, 'w', encoding='utf-8') as f:
                json.dump(backup, f, indent=2, ensure_ascii=False)
        except Exception as e:
            QMessageBox.critical(self, self._("Export error"), str(e))
            return

        QMessageBox.information(self, self._("Export completed"),
                                self._("Exported {} hosts to:\n{}").format(len(hosts_data), file_name))

    # ---------- Tray icon ----------

    def _make_badge_icon(self, base_color_hex, count):
        """Icon with a number inside: count > 0 draws the badge. Cached."""
        if count <= 0:
            return self.create_icon(base_color_hex)
        key = (base_color_hex, min(count, 99))
        cached = self._icon_cache.get(key)
        if cached is not None:
            return cached

        icon = QIcon()
        for size in (16, 22, 24, 32, 48, 64, 128, 256):
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.GlobalColor.transparent)
            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            margin = max(1, size // 16)
            painter.setBrush(QColor(base_color_hex))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(margin, margin,
                                size - 2 * margin, size - 2 * margin)
            label = str(count) if count < 100 else "99+"
            font_size = int(size * (0.62 if count < 10 else 0.5))
            painter.setPen(QColor("white"))
            painter.setFont(QFont("Arial", max(7, font_size), QFont.Weight.Bold))
            painter.drawText(pixmap.rect(),
                             Qt.AlignmentFlag.AlignCenter, label)
            painter.end()
            icon.addPixmap(pixmap)

        self._icon_cache[key] = icon
        return icon

    def update_app_icon(self):
        down_count = sum(
            1 for w in self.host_widgets.values()
            if not w.disabled and not w.muted
            and w.consecutive_failures >= self.alerts_after_failures
        )
        has_yellow = any(
            1 <= w.consecutive_failures < self.alerts_after_failures
            for w in self.host_widgets.values()
            if not w.disabled and not w.muted
        )
        if down_count > 0:
            new_icon = self._make_badge_icon("#F44336", down_count)
        elif has_yellow:
            new_icon = self.yellow_icon
        else:
            new_icon = self.green_icon

        if new_icon is not self._current_icon:
            self._current_icon = new_icon
            self.setWindowIcon(new_icon)
            self.tray_icon.setIcon(new_icon)

    # ---------- Queues ----------

    def update_host_queue(self):
        self.icmp_queue = []
        self.tcp_queue = []

        def traverse(pi):
            for i in range(pi.childCount()):
                c = pi.child(i)
                host = c.data(0, Qt.ItemDataRole.UserRole)
                if not host or host not in self.host_widgets:
                    continue
                w = self.host_widgets[host]
                if w.disabled:
                    continue
                info = self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                if info.get('type') == 'tcp':
                    self.tcp_queue.append(host)
                else:
                    self.icmp_queue.append(host)

        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))

        self.icmp_idx = 0
        self.tcp_idx = 0

    def start_pinging(self):
        if self.host_widgets:
            self.update_host_queue()
            if not self.ping_timer.isActive():
                self.ping_timer.start(self.interval_slider.value())

    # ---------- Highlight ----------

    def _clear_highlight(self):
        p = palette()
        for h in self._highlighted_hosts:
            self._set_host_bg(h, p.clear_bg)
        self._highlighted_hosts = []

    def _set_host_bg(self, host, color):
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.data(0, Qt.ItemDataRole.UserRole) == host:
                    hi.setBackground(0, color)
                    return

    def _host_color(self, widget):
        p = palette()
        if widget.disabled:
            return p.host_disabled
        if widget.consecutive_failures >= self.alerts_after_failures:
            return p.host_down
        if widget.consecutive_failures >= 1:
            return p.host_warn
        return p.host_normal

    def _set_host_color(self, host):
        w = self.host_widgets.get(host)
        if not w:
            return
        color = self._host_color(w)
        for i in range(self.host_list.topLevelItemCount()):
            ci = self.host_list.topLevelItem(i)
            for j in range(ci.childCount()):
                hi = ci.child(j)
                if hi.data(0, Qt.ItemDataRole.UserRole) == host:
                    hi.setForeground(0, color)
                    return

    def _take_next_icmp_batch(self):
        if not self.icmp_queue:
            return []
        n = min(self.fping_batch_size, len(self.icmp_queue))
        batch = []
        for _ in range(n):
            if self.icmp_idx >= len(self.icmp_queue):
                self.icmp_idx = 0
            h = self.icmp_queue[self.icmp_idx]
            self.icmp_idx = (self.icmp_idx + 1) % len(self.icmp_queue)
            if h not in batch:
                batch.append(h)
            if len(batch) >= len(self.icmp_queue):
                break
        return batch

    def _take_next_tcp(self):
        if not self.tcp_queue:
            return None
        if self.tcp_idx >= len(self.tcp_queue):
            self.tcp_idx = 0
        h = self.tcp_queue[self.tcp_idx]
        self.tcp_idx = (self.tcp_idx + 1) % len(self.tcp_queue)
        return h

    # ---------- Tick ----------

    def ping_tick(self):
        if not self.host_widgets:
            return
        self._clear_highlight()
        scheduled = []

        if self.icmp_queue:
            if has_fping():
                batch = self._take_next_icmp_batch()
                if batch:
                    self.ping_manager.ping_icmp_batch(batch)
                    scheduled.extend(batch)
            else:
                if self.icmp_idx >= len(self.icmp_queue):
                    self.icmp_idx = 0
                h = self.icmp_queue[self.icmp_idx]
                self.icmp_idx = (self.icmp_idx + 1) % len(self.icmp_queue)
                self.ping_manager.ping_host(h, 'icmp', None)
                scheduled.append(h)

        h_tcp = self._take_next_tcp()
        if h_tcp is not None:
            info = self.host_check_types.get(h_tcp, {'type': 'tcp', 'port': None})
            self.ping_manager.ping_host(h_tcp, 'tcp', info.get('port'))
            scheduled.append(h_tcp)

        p = palette()
        for h in scheduled:
            self._set_host_bg(h, p.highlight_bg)
        self._highlighted_hosts = scheduled

    # ---------- Ping result ----------

    def handle_ping_result(self, host, success, latency):
        current_time = datetime.now()
        if host in self.host_widgets:
            w = self.host_widgets[host]
            if w.disabled:
                return
            consecutive = w.update_status(success, latency, current_time)

            if success:
                if w.was_down:
                    w.was_down = False
                    self.fire_hook("up", host, failures=0)
                    if (self.notify_on_recovery
                            and self.notifications_enabled
                            and not w.muted):
                        self._queue_notification("up", host)
                w.last_notified = None
            else:
                if consecutive >= self.alerts_after_failures:
                    if not w.was_down:
                        w.was_down = True
                        self.fire_hook("down", host, failures=consecutive)
                    if self.notifications_enabled and not w.muted:
                        last = w.last_notified
                        if (last is None
                                or (current_time - last).total_seconds()
                                    >= self.alert_reminder_minutes * 60):
                            w.last_notified = current_time
                            print(f"[notify] host={host} fails={consecutive}")
                            self._queue_notification("down", host, consecutive)

        self.update_app_icon()
        if host in self.host_widgets:
            self._set_host_color(host)
        self.apply_filter()

    # ---------- Add / edit ----------

    def add_host(self):
        host = self.host_input.text().strip()
        if host and host not in self.host_widgets:
            w = self._make_host_widget(host, "Default")
            self.host_widgets[host] = w
            self._load_single_host_history(host, w)
            self.update_host_list_display()
            self.reorder_graphs()
            self.host_input.clear()
            self.save_data()
            self.apply_filter()
            if not self.ping_timer.isActive():
                self.start_pinging()
            else:
                self.update_host_queue()

    def update_interval(self, interval):
        self.interval_label.setText(self._("Interval: {}ms").format(interval))
        self.ping_manager.set_ping_interval(interval)
        self.settings.setValue("interval", interval)
        for w in self.host_widgets.values():
            w.graph_widget.set_check_interval(interval)
        if self.ping_timer.isActive():
            self.ping_timer.start(interval)

    def _rename_host_history_dir(self, old_host, new_host):
        old_dir = self._host_dir(old_host)
        new_dir = self._host_dir(new_host)
        try:
            os.makedirs(new_dir, exist_ok=True)

            if os.path.isdir(old_dir) and os.path.realpath(old_dir) != os.path.realpath(new_dir):
                for fname in os.listdir(old_dir):
                    src = os.path.join(old_dir, fname)
                    dst = os.path.join(new_dir, fname)
                    if not os.path.isfile(src):
                        continue
                    if fname == 'meta.json':
                        try:
                            if os.path.exists(dst):
                                os.remove(dst)
                            shutil.move(src, dst)
                        except OSError as e:
                            print(f"[rename] meta move: {e}")
                    elif fname.endswith('.jsonl'):
                        if os.path.exists(dst):
                            try:
                                with open(src, 'r') as sf, open(dst, 'a') as df:
                                    df.write(sf.read())
                                os.remove(src)
                            except OSError as e:
                                print(f"[rename] merge {fname}: {e}")
                        else:
                            try:
                                shutil.move(src, dst)
                            except OSError as e:
                                print(f"[rename] move {fname}: {e}")
                    else:
                        try:
                            shutil.move(src, dst)
                        except OSError as e:
                            print(f"[rename] move {fname}: {e}")

                try:
                    if os.path.isdir(old_dir) and not os.listdir(old_dir):
                        os.rmdir(old_dir)
                except OSError:
                    pass

            with open(os.path.join(new_dir, 'meta.json'), 'w') as mf:
                json.dump({
                    'host': new_host,
                    'check_type': self.host_check_types.get(
                        new_host, {'type': 'icmp', 'port': None}),
                }, mf, indent=2)
        except Exception as e:
            print(f"[rename] Failed to rename history {old_dir} -> {new_dir}: {e}")

    def edit_host(self, host):
        if not host:
            return
        new_host, ok = QInputDialog.getText(self, self._("Edit"),
                                            self._("New host name:"), text=host)
        if not (ok and new_host and new_host.strip() and new_host != host):
            return
        new_host = new_host.strip()
        if new_host in self.host_widgets:
            QMessageBox.warning(self, self._("Edit"),
                                self._("Host '{}' already exists.").format(new_host))
            return

        w = self.host_widgets[host]

        if host in self.host_check_types:
            self.host_check_types[new_host] = self.host_check_types.pop(host)

        self._rename_host_history_dir(host, new_host)

        w.host = new_host
        w.graph_widget.host = new_host
        w.update_host_label()

        new_widgets = {}
        for h, wdg in self.host_widgets.items():
            if h == host:
                new_widgets[new_host] = wdg
            else:
                new_widgets[h] = wdg
        self.host_widgets = new_widgets

        self.update_host_list_display()
        self.reorder_graphs()
        self.save_data()
        self.apply_filter()
        self.update_host_queue()

        self._select_host_in_tree(new_host)

    # ---------- Save ----------

    def _build_snapshot(self):
        snap = {}
        for host, w in self.host_widgets.items():
            last_saved = w.last_saved_time
            new = [(t, s, lat) for (t, s, lat) in w.ping_history
                   if last_saved is None or t > last_saved]
            snap[host] = {
                'dir': self._host_dir(host),
                'records': new,
                'meta': {
                    'host': host,
                    'check_type': self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                },
            }
        return snap

    def save_data(self):
        hosts = []
        def traverse(pi):
            cat_name = pi.data(0, Qt.ItemDataRole.UserRole)
            for i in range(pi.childCount()):
                c = pi.child(i)
                h = c.data(0, Qt.ItemDataRole.UserRole)
                if h and h in self.host_widgets:
                    w = self.host_widgets[h]
                    if cat_name:
                        w.category = cat_name
                    hosts.append([h, w.category, bool(w.disabled), bool(w.muted)])
        for i in range(self.host_list.topLevelItemCount()):
            traverse(self.host_list.topLevelItem(i))
        self.settings.setValue("hosts", hosts)
        self.settings.setValue("filter_mode", self.filter_mode)
        self.settings.setValue("categories", self.categories_list)
        self.settings.setValue("retention_hours", self.retention_hours)
        self.settings.setValue("minimize_on_escape", self.minimize_on_escape)
        self.settings.setValue("alerts_after_failures", self.alerts_after_failures)
        self.settings.setValue("alert_reminder_minutes", self.alert_reminder_minutes)
        self.settings.setValue("notify_on_recovery", self.notify_on_recovery)
        self.settings.setValue("cleanup_enabled", self.cleanup_enabled)
        self.settings.setValue("cleanup_days", self.cleanup_days)
        self.settings.setValue("hooks_enabled", self.hooks_enabled)
        self.settings.setValue("hooks_dir", self.hooks_dir)
        self.settings.setValue("fping_batch_size", self.fping_batch_size)
        self.settings.setValue("ping_timeout_ms", self.ping_timeout_ms)
        self.settings.setValue("appearance", self.appearance)
        self.settings.setValue("graph_show_latency", self.graph_show_latency)
        self.settings.setValue("graph_height_mode", self.graph_height_mode)

        if self._save_in_progress:
            return
        snap = self._build_snapshot()
        self._save_in_progress = True
        worker = SaveWorker(snap)
        self._save_workers.add(worker)
        worker.signals.finished.connect(
            lambda r, w=worker: self._on_save_finished(r, w)
        )
        self.thread_pool.start(worker)

    def _save_data_sync(self):
        self.save_data()
        self.thread_pool.waitForDone(3000)
        for host, w in self.host_widgets.items():
            last_saved = w.last_saved_time
            new = [(t, s, lat) for (t, s, lat) in w.ping_history
                   if last_saved is None or t > last_saved]
            if not new:
                continue
            try:
                hd = self._host_dir(host)
                os.makedirs(hd, exist_ok=True)
                with open(os.path.join(hd, "meta.json"), 'w') as mf:
                    json.dump({
                        'host': host,
                        'check_type': self.host_check_types.get(host, {'type': 'icmp', 'port': None})
                    }, mf, indent=2)
                by_day = {}
                for t, s, lat in new:
                    key = t.strftime("%Y-%m-%d")
                    by_day.setdefault(key, []).append((t, s, lat))
                for day, recs in by_day.items():
                    path = os.path.join(hd, f"{day}.jsonl")
                    with open(path, 'a') as f:
                        for t, s, lat in recs:
                            f.write(json.dumps([t.isoformat(), s, lat]) + "\n")
                w.last_saved_time = max(t for t, _, _ in new)
            except Exception as e:
                print(f"[save-sync] {host}: {e}")

    @pyqtSlot(dict)
    def _on_save_finished(self, result, worker=None):
        if worker is not None:
            self._save_workers.discard(worker)
        for host, latest in result.items():
            if host in self.host_widgets and latest is not None:
                self.host_widgets[host].last_saved_time = latest
        self._save_in_progress = False

    # ---------- Load ----------

    def _load_single_host_history(self, host, widget):
        host_dir = self._host_dir(host)
        if not os.path.isdir(host_dir):
            return 0

        meta_path = os.path.join(host_dir, "meta.json")
        check_info = {'type': 'icmp', 'port': None}
        if os.path.exists(meta_path):
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
                check_info = meta.get('check_type', check_info)
            except Exception as e:
                print(f"Error reading meta for {host}: {e}")
        self.host_check_types[host] = check_info
        widget.set_check_type(check_info['type'], check_info.get('port'))

        now = datetime.now()
        initial_days = _days_between(now - timedelta(hours=1), now)
        existing = set(list_history_days(host_dir))
        days_to_load = sorted(initial_days & existing)

        records, latest_time = read_history_days(host_dir, days_to_load)

        widget.ping_history = records
        widget.loaded_days = set(days_to_load)
        widget.last_saved_time = latest_time

        failures = 0
        for _, s, _ in reversed(records):
            if not s:
                failures += 1
            else:
                break
        widget.consecutive_failures = failures

        widget.graph_widget.update_history(
            widget.ping_history, widget.session_success_count,
            widget.session_failure_count, self.app_start_time)
        return len(records)

    def load_data(self):
        hosts = self.settings.value("hosts", [], type=list)
        for hd in hosts:
            disabled = False
            muted = False
            if isinstance(hd, (list, tuple)) and len(hd) >= 2:
                host, category = hd[0], hd[1]
                disabled = bool(hd[2]) if len(hd) > 2 else False
                muted = bool(hd[3]) if len(hd) > 3 else False
            else:
                host = hd if isinstance(hd, str) else str(hd)
                category = "Default"
            if isinstance(host, str) and host:
                if category not in self.categories_list:
                    self.categories_list.append(category)
                w = self._make_host_widget(host, category)
                w.set_disabled(disabled)
                w.set_muted(muted)
                self.host_widgets[host] = w

        for host, w in self.host_widgets.items():
            loaded = self._load_single_host_history(host, w)
            if loaded:
                print(f"[load] Loaded {loaded} records for {host}")

        self.update_host_list_display()
        self.reorder_graphs()
        self.apply_filter()
        self.update_host_queue()

        if self.host_widgets:
            self.start_pinging()

    def update_all_graphs(self):
        for w in self.host_widgets.values():
            w.graph_widget.update_history(
                w.ping_history, w.session_success_count,
                w.session_failure_count, self.app_start_time)


def main_entry():
    """Entry point for console_scripts (used by Snap, pip install)."""
    app = QApplication(sys.argv)
    window = PingMonitor()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main_entry())
